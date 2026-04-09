from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import json
import time
import asyncio
from collections import Counter

from .config import settings
from .github_client import get_user_profile, get_repos, get_readme
from .readme_analyzer import analyze_readme

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
        raise HTTPException(status_code=404, detail=str(e))

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
    """
    try:
        repos = await get_repos(username, settings.github_token)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

    report = []
    for repo in repos:
        name = repo.get("name")
        try:
            content = await get_readme(username, name, settings.github_token)
            analysis = await analyze_readme(content)
            report.append({"repo": name, "analysis": analysis})
        except Exception:
            continue

    return {"reports": report}


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
        raise HTTPException(status_code=404, detail=str(e))
    await cache_set(cache_key, {"repos": repos}, ttl=600)
    return {"repos": repos}


@app.get("/health")
async def health():
    return {"status": "ok"}
