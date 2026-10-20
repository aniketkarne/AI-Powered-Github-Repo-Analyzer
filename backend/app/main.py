from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import json
import time
import asyncio
from collections import Counter

import httpx

from .config import settings
from .github_client import get_user_profile, get_repos, get_readme
from .readme_analyzer import analyze_readme


def _raise_from_github_error(exc: Exception, username: str = "") -> "HTTPException":
    """
    Map GitHub API errors to a useful HTTP response for the caller.

    GitHub returns 403 for both "user not found" (on /users/{name}) when the
    account is hidden, and for rate-limit exhaustion. The previous code path
    collapsed every GitHub error to HTTP 404, which is wrong: a rate-limited
    caller was told "user not found" and had no signal to back off.

    This helper distinguishes the two cases by inspecting the GitHub error
    body when available:
      * 404 from /users/{name}                  -> 404 (genuine missing user)
      * 403 with X-RateLimit-Remaining=0       -> 503 + Retry-After
        (or a body mentioning "rate limit")
      * 403 with no rate-limit signal           -> 404 (hidden / blocked)
      * 401                                      -> 500 (server's token wrong)
      * other                                    -> 502 (bad gateway)

    ``username`` is best-effort context for the 404 detail string; pass it
    in where available.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        # Try to read GitHub's message + rate-limit headers
        retry_after = exc.response.headers.get("Retry-After")
        rl_remaining = exc.response.headers.get("X-RateLimit-Remaining")
        rl_reset = exc.response.headers.get("X-RateLimit-Reset")
        try:
            body = exc.response.json()
        except Exception:
            body = {}
        msg = (body.get("message") or "").lower()

        # Rate limit hit (GitHub returns 403 with X-RateLimit-Remaining: 0
        # or a body starting with "API rate limit exceeded").
        if (
            status == 403
            and (rl_remaining == "0" or "rate limit" in msg)
        ):
            headers = {}
            if retry_after:
                headers["Retry-After"] = retry_after
            elif rl_reset:
                # X-RateLimit-Reset is a unix timestamp; convert to seconds-from-now.
                try:
                    secs = max(1, int(rl_reset) - int(time.time()))
                    headers["Retry-After"] = str(secs)
                except (TypeError, ValueError):
                    pass
            return HTTPException(
                status_code=503,
                detail="GitHub API rate limit hit; retry shortly",
                headers=headers or None,
            )

        # Any other 403 is GitHub's "you can't see this" — surface as 404 so
        # the API user gets a consistent missing-or-hidden semantics instead
        # of a raw GitHub error code they have no context for.
        if status == 403:
            return HTTPException(status_code=404, detail=f"Not found or not accessible: {username}")

        if status == 404:
            return HTTPException(status_code=404, detail=str(exc))
        if status == 401:
            return HTTPException(status_code=500, detail="GitHub auth failed; check GITHUB_TOKEN")
        return HTTPException(status_code=502, detail=f"GitHub error: {exc}")

    # Non-HTTP error (network, timeout) — surface as 502 so callers know it's
    # transient rather than "user not found".
    return HTTPException(status_code=502, detail=f"GitHub request failed: {exc}")

app = FastAPI(title="GitHub Repo Analyzer API", version="1.0.0")

# Simple in-memory cache: {key: (expires_at, data)}
_cache: dict = {}
_cache_lock = asyncio.Lock()


async def cache_get(key: str):
    async with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        expires_at, data = entry
        if time.time() > expires_at:
            del _cache[key]
            return None
        return data


async def cache_set(key: str, data, ttl: int = 600):
    async with _cache_lock:
        _cache[key] = (time.time() + ttl, data)


origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/profile/{username}")
async def profile(username: str):
    """
    Fetch GitHub user profile with repository stats:
    - Avatar, bio, follower/following counts
    - Language breakdown across all repos
    - Top repos by stars and forks
    - Activity heatmap (push timestamps)
    """
    cache_key = f"profile:{username}"
    cached = await cache_get(cache_key)
    if cached:
        return cached
    try:
        profile_data = await get_user_profile(username, settings.github_token)
        repos = await get_repos(username, settings.github_token)
    except Exception as e:
        raise _raise_from_github_error(e, username)

    langs = [repo["language"] or "Unknown" for repo in repos]
    cnt = Counter(langs)
    total = sum(cnt.values()) or 1
    language_breakdown = [
        {"language": lang, "count": num, "percent": round(num / total * 100, 2)}
        for lang, num in cnt.items()
    ]
    star_trend = sorted(
        [{"repo": r["name"], "stars": r["stars"]} for r in repos],
        key=lambda x: x["stars"],
        reverse=True
    )
    fork_trend = sorted(
        [{"repo": r["name"], "forks": r["forks"]} for r in repos],
        key=lambda x: x["forks"],
        reverse=True
    )
    heatmap = [r["pushed_at"] for r in repos]

    result = {
        "profile": profile_data,
        "repos": repos,
        "language_breakdown": language_breakdown,
        "star_trend": star_trend,
        "fork_trend": fork_trend,
        "heatmap": heatmap
    }
    await cache_set(cache_key, result, ttl=600)
    return result


@app.get("/api/profile/{username}/readme-report")
async def readme_report(username: str):
    """
    Analyze README files for all of a user's public repositories.
    Returns summary, suggestions, readability score, and missing sections per repo.

    This endpoint fans out (N GitHub fetches + N OpenAI calls) per request,
    so the result is cached for README_REPORT_TTL seconds (default 10 min)
    keyed by username. A cache miss on a token-less deployment will hit the
    GitHub rate limit after one request — treat cached responses as best-effort.
    """
    README_REPORT_TTL = 600  # seconds
    cache_key = f"readme_report:{username}"
    cached = await cache_get(cache_key)
    if cached:
        return cached
    try:
        repos = await get_repos(username, settings.github_token)
    except Exception as e:
        raise _raise_from_github_error(e, username)

    report = []
    failed = 0
    for repo in repos:
        name = repo.get("name")
        try:
            content = await get_readme(username, name, settings.github_token)
            analysis = await analyze_readme(content)
            report.append({"repo": name, "analysis": analysis})
        except httpx.HTTPStatusError:
            # GitHub error reading one repo's README (often 404 for empty
            # repos or 403 mid-pagination). Don't fail the whole request —
            # record the miss so the caller knows the report is partial.
            failed += 1
        except Exception:
            # analyze_readme failure (missing OPENAI_API_KEY, JSON parse,
            # transient OpenAI 5xx). Same partial-report semantics.
            failed += 1

    result = {"reports": report, "failed": failed}
    await cache_set(cache_key, result, ttl=README_REPORT_TTL)
    return result


@app.get("/api/profile/{username}/repos")
async def repos_only(username: str):
    """
    Fetch all public repos for a user with basic metadata.
    Lightweight alternative to the full profile endpoint.
    """
    cache_key = f"repos:{username}"
    cached = await cache_get(cache_key)
    if cached:
        return cached
    try:
        repos = await get_repos(username, settings.github_token)
    except Exception as e:
        raise _raise_from_github_error(e, username)
    await cache_set(cache_key, {"repos": repos}, ttl=600)
    return {"repos": repos}


@app.get("/health")
async def health():
    return {"status": "ok"}
