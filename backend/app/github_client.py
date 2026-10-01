import httpx

GITHUB_API = "https://api.github.com"

# Hard cap on how many repos we'll fetch in one request. GitHub's
# unauthenticated rate limit is 60 req/hr; even one full pull from a
# 5000-repo user can chew through ~50 requests on the first cache miss.
# Capping at 600 keeps the worst-case below 7 requests and prevents a
# runaway loop if GitHub ever returns a partial page followed by an
# empty one. Callers needing more can override via `max_repos`.
DEFAULT_MAX_REPOS = 600

# `type=owner` is the safest default for a public analyzer: only repos
# the user owns on their personal account, no org repos unless the
# caller explicitly asks. GitHub's default is `type=all` which leaks
# private repos visible to the supplied token. Forcing `owner` here
# means a stray `GITHUB_TOKEN` accidentally pasted into a public
# deployment won't dump private repos.
DEFAULT_REPO_TYPE = "owner"


async def get_user_profile(username: str, token: str) -> dict:
    headers = {"Authorization": f"token {token}"} if token else {}
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{GITHUB_API}/users/{username}", headers=headers)
        resp.raise_for_status()
        return resp.json()


async def get_repos(
    username: str,
    token: str,
    *,
    max_repos: int = DEFAULT_MAX_REPOS,
    repo_type: str = DEFAULT_REPO_TYPE,
) -> list:
    """Fetch all public repos for `username`, bounded by `max_repos`.

    `repo_type` defaults to ``"owner"`` so the analyzer only returns repos
    the user owns on their personal account. This avoids leaking private
    repos a stray token can see (GitHub's default ``type=all`` would).
    """
    headers = {"Authorization": f"token {token}"} if token else {}
    repos = []
    page = 1
    per_page = 100
    async with httpx.AsyncClient() as client:
        while True:
            resp = await client.get(
                f"{GITHUB_API}/users/{username}/repos",
                params={
                    "per_page": per_page,
                    "page": page,
                    "sort": "pushed",
                    "type": repo_type,
                },
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            if not data:
                break
            repos.extend(data)
            if len(repos) >= max_repos:
                repos = repos[:max_repos]
                break
            if len(data) < per_page:
                break
            page += 1
    return [
        {
            "name": repo["name"],
            "description": repo.get("description"),
            "stars": repo.get("stargazers_count"),
            "forks": repo.get("forks_count"),
            "language": repo.get("language"),
            "pushed_at": repo.get("pushed_at"),
        }
        for repo in repos
    ]


async def get_readme(username: str, repo_name: str, token: str) -> str:
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3.raw",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GITHUB_API}/repos/{username}/{repo_name}/readme",
            headers=headers,
        )
        resp.raise_for_status()
        return resp.text