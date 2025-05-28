import httpx

GITHUB_API = "https://api.github.com"

async def get_user_profile(username: str, token: str) -> dict:
    headers = {"Authorization": f"token {token}"} if token else {}
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{GITHUB_API}/users/{username}", headers=headers)
        resp.raise_for_status()
        return resp.json()

async def get_repos(username: str, token: str) -> list:
    headers = {"Authorization": f"token {token}"} if token else {}
    repos = []
    page = 1
    per_page = 100
    async with httpx.AsyncClient() as client:
        while True:
            resp = await client.get(
                f"{GITHUB_API}/users/{username}/repos",
                params={"per_page": per_page, "page": page, "sort": "pushed"},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            if not data:
                break
            repos.extend(data)
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
        "Accept": "application/vnd.github.v3.raw"
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GITHUB_API}/repos/{username}/{repo_name}/readme",
            headers=headers
        )
        resp.raise_for_status()
        return resp.text