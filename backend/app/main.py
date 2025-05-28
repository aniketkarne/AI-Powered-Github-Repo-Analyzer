from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import json
import aioredis
from collections import Counter

from .config import settings
from .github_client import get_user_profile, get_repos, get_readme
from .readme_analyzer import analyze_readme
import openai
from fastapi import Body

app = FastAPI()
redis = aioredis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)

origins = ["*"]  # TODO: restrict origins in production

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
    Fetch user profile and repository list.
    """
    cache_key = f"profile:{username}"
    cached = await redis.get(cache_key)
    if cached:
        return json.loads(cached)
    try:
        profile_data = await get_user_profile(username, settings.github_token)
        repos = await get_repos(username, settings.github_token)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
    # Language breakdown
    langs = [repo["language"] or "Unknown" for repo in repos]
    cnt = Counter(langs)
    total = sum(cnt.values()) or 1
    language_breakdown = [
        {"language": lang, "count": num, "percent": round(num / total * 100, 2)}
        for lang, num in cnt.items()
    ]
    # Star & fork trends
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
    # Activity heatmap (push dates)
    heatmap = [r["pushed_at"] for r in repos]
    result = {
        "profile": profile_data,
        "repos": repos,
        "language_breakdown": language_breakdown,
        "star_trend": star_trend,
        "fork_trend": fork_trend,
        "heatmap": heatmap
    }
    await redis.set(cache_key, json.dumps(result), ex=600)
    return result

@app.get("/api/profile/{username}/readme-report")
async def readme_report(username: str):
    """
    Analyze README files for each repository.
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