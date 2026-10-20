"""
Tests for backend/app/main.py covering two related concerns:

  1. /api/profile/{username}/readme-report must cache its result so the
     GitHub + OpenAI fan-out (N repos => N+N requests) doesn't repeat on
     every poll. The other endpoints already cache; readme-report didn't.

  2. /api/profile/{username}/* must distinguish GitHub rate-limit errors
     (HTTP 403) from genuine 404s. The previous code path collapsed every
     GitHub error to HTTP 404, so a rate-limited caller was told "user
     not found" with no signal to back off. New behaviour: 403 with
     X-RateLimit-Remaining=0 (or a body mentioning "rate limit") =>
     503 + Retry-After. 404 from /users/{name} => 404.

We use FastAPI's TestClient and monkey-patch the four module-level names
that ``app.main`` imports (``get_user_profile``, ``get_repos``,
``get_readme``, ``analyze_readme``). No network, no GitHub creds.
"""

import httpx
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


@pytest.fixture
def patched_github(monkeypatch):
    """Patch the github_client helpers with constants we control.

    Returns a dict the test can inspect for call counts. Call
    ``install_call_counters`` once to upgrade the patches to also track
    invocations.
    """
    from app import main as main_mod

    counters = {"repos": 0, "readme": 0, "analyze": 0, "profile": 0}

    repos_data = [
        {"name": "alpha", "description": "A", "stars": 1, "forks": 0,
         "language": "Python", "pushed_at": "2025-01-01T00:00:00Z"},
        {"name": "beta", "description": "B", "stars": 2, "forks": 0,
         "language": "Go", "pushed_at": "2025-02-01T00:00:00Z"},
    ]

    async def fake_repos(username, token):
        counters["repos"] += 1
        return repos_data

    async def fake_readme(username, repo, token):
        counters["readme"] += 1
        return f"# {repo}\n\nInstallation\n\nUsage\n\nLicense\n\nContributing"

    async def fake_analyze(content):
        counters["analyze"] += 1
        return {"summary": "ok", "suggestions": []}

    profile_data = {"login": "alice", "name": "Alice",
                    "avatar_url": "https://example/avatar.png", "bio": "",
                    "followers": 10, "following": 5, "public_repos": 2}

    async def fake_profile(username, token):
        counters["profile"] += 1
        return profile_data

    monkeypatch.setattr(main_mod, "get_user_profile", fake_profile)
    monkeypatch.setattr(main_mod, "get_repos", fake_repos)
    monkeypatch.setattr(main_mod, "get_readme", fake_readme)
    monkeypatch.setattr(main_mod, "analyze_readme", fake_analyze)
    return {"repos": repos_data, "profile": profile_data, "counters": counters}


# ---------------------------------------------------------------------------
# readme-report caching
# ---------------------------------------------------------------------------

def test_readme_report_returns_reports_and_failed_count(client, patched_github):
    """First call hits the helpers, builds a report shape, includes the failed counter."""
    resp = client.get("/api/profile/alice/readme-report")
    assert resp.status_code == 200
    body = resp.json()
    assert body["failed"] == 0
    assert len(body["reports"]) == 2
    assert {r["repo"] for r in body["reports"]} == {"alpha", "beta"}
    assert patched_github["counters"]["repos"] == 1
    assert patched_github["counters"]["readme"] == 2
    assert patched_github["counters"]["analyze"] == 2


def test_readme_report_serves_from_cache_on_second_call(client, patched_github):
    """Second identical request must NOT re-invoke GitHub or OpenAI."""
    first = client.get("/api/profile/alice/readme-report")
    second = client.get("/api/profile/alice/readme-report")
    assert first.status_code == 200
    assert second.status_code == 200
    # Body must be identical (cache hit means same dict).
    assert first.json() == second.json()
    assert patched_github["counters"]["repos"] == 1, "repos must be fetched only once across two calls"
    assert patched_github["counters"]["readme"] == 2, "only the first call should hit get_readme"
    assert patched_github["counters"]["analyze"] == 2, "only the first call should hit OpenAI"


def test_readme_report_distinct_users_dont_collide(client, patched_github):
    """Two different usernames must each have their own cache entry."""
    r1 = client.get("/api/profile/alice/readme-report")
    r2 = client.get("/api/profile/bob/readme-report")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert patched_github["counters"]["repos"] == 2


def test_readme_report_partial_failure_increments_failed(client, monkeypatch):
    """If one repo's README 404s (or OpenAI 5xx), that repo is skipped and failed ticks up.

    A previous version of the code returned {"reports": [...]} with the failed
    repo silently dropped and no way for the caller to tell the report was
    partial. New contract: 'failed' counts how many repos the loop skipped.
    """
    from app import main as main_mod
    repos_data = [
        {"name": "ok-1", "description": "", "stars": 0, "forks": 0,
         "language": "Python", "pushed_at": "2025-01-01T00:00:00Z"},
        {"name": "gh-404", "description": "", "stars": 0, "forks": 0,
         "language": "Python", "pushed_at": "2025-01-01T00:00:00Z"},
        {"name": "ok-2", "description": "", "stars": 0, "forks": 0,
         "language": "Python", "pushed_at": "2025-01-01T00:00:00Z"},
    ]

    async def fake_repos(username, token):
        return repos_data

    async def fake_readme(username, repo, token):
        if repo == "gh-404":
            # httpx.HTTPStatusError mirrors GitHub's behaviour on a repo with
            # no README (legacy), a banned repo, or mid-pagination 403.
            req = httpx.Request("GET", f"https://api.github.com/repos/{username}/{repo}/readme")
            resp = httpx.Response(404, request=req)
            raise httpx.HTTPStatusError("Not Found", request=req, response=resp)
        return f"# {repo}\n\nInstallation\n\nUsage\n\nLicense\n\nContributing"

    async def fake_analyze(content):
        return {"summary": "ok", "suggestions": []}

    async def fake_profile(username, token):
        return {"login": username, "name": username, "avatar_url": "",
                "bio": "", "followers": 0, "following": 0, "public_repos": 3}

    monkeypatch.setattr(main_mod, "get_user_profile", fake_profile)
    monkeypatch.setattr(main_mod, "get_repos", fake_repos)
    monkeypatch.setattr(main_mod, "get_readme", fake_readme)
    monkeypatch.setattr(main_mod, "analyze_readme", fake_analyze)

    resp = client.get("/api/profile/alice/readme-report")
    assert resp.status_code == 200
    body = resp.json()
    names = {r["repo"] for r in body["reports"]}
    assert names == {"ok-1", "ok-2"}
    assert body["failed"] == 1


def test_readme_report_404_on_missing_user_does_not_cache(client, monkeypatch):
    """When get_repos raises 404, we don't cache it (a transient Github failure
    shouldn't poison the cache), and the response is 404 not 503."""
    from app import main as main_mod

    async def fake_repos_404(username, token):
        req = httpx.Request("GET", f"https://api.github.com/users/{username}/repos")
        resp = httpx.Response(404, request=req)
        raise httpx.HTTPStatusError("Not Found", request=req, response=resp)

    async def fake_profile(username, token):
        req = httpx.Request("GET", f"https://api.github.com/users/{username}")
        resp = httpx.Response(404, request=req)
        raise httpx.HTTPStatusError("Not Found", request=req, response=resp)

    monkeypatch.setattr(main_mod, "get_user_profile", fake_profile)
    monkeypatch.setattr(main_mod, "get_repos", fake_repos_404)
    # get_readme won't be called because get_repos raises first.
    async def should_not_be_called(*a, **kw):
        raise AssertionError("get_readme must NOT be called when get_repos raises")
    monkeypatch.setattr(main_mod, "get_readme", should_not_be_called)
    async def should_not_be_called2(*a, **kw):
        raise AssertionError("analyze_readme must NOT be called when get_repos raises")
    monkeypatch.setattr(main_mod, "analyze_readme", should_not_be_called2)

    resp = client.get("/api/profile/ghost/readme-report")
    assert resp.status_code == 404

    # And the failure must NOT have been cached — second call must re-hit
    # get_repos (otherwise a transient 404 becomes permanent).
    called = {"n": 0}
    async def fake_repos_404_counted(username, token):
        called["n"] += 1
        req = httpx.Request("GET", f"https://api.github.com/users/{username}/repos")
        resp = httpx.Response(404, request=req)
        raise httpx.HTTPStatusError("Not Found", request=req, response=resp)
    monkeypatch.setattr(main_mod, "get_repos", fake_repos_404_counted)

    resp2 = client.get("/api/profile/ghost/readme-report")
    assert resp2.status_code == 404
    assert called["n"] == 1, "404 must NOT have been cached"


# ---------------------------------------------------------------------------
# GitHub error -> HTTP status mapping
# ---------------------------------------------------------------------------

def _make_http_error(status, body=None, headers=None):
    headers = headers or {}
    body = body or {}
    req = httpx.Request("GET", "https://api.github.com/users/alice")
    resp = httpx.Response(status, request=req, headers=headers, json=body)
    return httpx.HTTPStatusError("err", request=req, response=resp)


def test_rate_limit_403_maps_to_503_with_retry_after(client, monkeypatch):
    """GitHub 403 with rate-limit headers must surface as 503 + Retry-After.

    The previous code unconditionally raised 404 for any GitHub failure, so a
    rate-limited caller saw 'user not found' and had no way to back off.
    """
    from app import main as main_mod

    async def fake_profile_403(username, token):
        raise _make_http_error(
            403,
            body={"message": "API rate limit exceeded for 1.2.3.4"},
            headers={"X-RateLimit-Remaining": "0",
                     "X-RateLimit-Reset": "9999999999"},
        )

    monkeypatch.setattr(main_mod, "get_user_profile", fake_profile_403)
    async def should_not_run(username, token):
        raise AssertionError("get_repos must not run when profile raised")
    monkeypatch.setattr(main_mod, "get_repos", should_not_run)

    resp = client.get("/api/profile/alice")
    assert resp.status_code == 503
    assert "Retry-After" in resp.headers
    assert "rate limit" in resp.json()["detail"].lower()


def test_rate_limit_with_retry_after_header(client, monkeypatch):
    """When GitHub sends a literal Retry-After header, we pass it through verbatim."""
    from app import main as main_mod

    async def fake_profile_403(username, token):
        raise _make_http_error(
            403,
            body={"message": "rate limit"},
            headers={"Retry-After": "120"},
        )

    monkeypatch.setattr(main_mod, "get_user_profile", fake_profile_403)
    async def never(username, token):
        raise AssertionError
    monkeypatch.setattr(main_mod, "get_repos", never)

    resp = client.get("/api/profile/alice")
    assert resp.status_code == 503
    assert resp.headers["Retry-After"] == "120"


def test_hidden_account_403_still_maps_to_404(client, monkeypatch):
    """GitHub returns 403 (not 404) for accounts that exist but the caller
    cannot see. Those should still map to 404 for the API user."""
    from app import main as main_mod

    async def fake_profile_hidden(username, token):
        raise _make_http_error(
            403,
            body={"message": "You must be signed in to view this user"},
            headers={},
        )

    monkeypatch.setattr(main_mod, "get_user_profile", fake_profile_hidden)
    async def never(username, token):
        raise AssertionError
    monkeypatch.setattr(main_mod, "get_repos", never)

    resp = client.get("/api/profile/alice")
    assert resp.status_code == 404


def test_404_on_missing_user_still_404(client, monkeypatch):
    """Genuine missing user keeps the 404 path."""
    from app import main as main_mod

    async def fake_profile_404(username, token):
        raise _make_http_error(404, body={"message": "Not Found"})

    monkeypatch.setattr(main_mod, "get_user_profile", fake_profile_404)
    async def never(username, token):
        raise AssertionError
    monkeypatch.setattr(main_mod, "get_repos", never)

    resp = client.get("/api/profile/ghost")
    assert resp.status_code == 404


def test_401_maps_to_500_with_actionable_detail(client, monkeypatch):
    """A bad GITHUB_TOKEN is a server config problem, not a 'user not found'.

    500 + 'check GITHUB_TOKEN' is more useful than 404 to the operator.
    """
    from app import main as main_mod

    async def fake_profile_401(username, token):
        raise _make_http_error(401, body={"message": "Bad credentials"})

    monkeypatch.setattr(main_mod, "get_user_profile", fake_profile_401)
    async def never(username, token):
        raise AssertionError
    monkeypatch.setattr(main_mod, "get_repos", never)

    resp = client.get("/api/profile/alice")
    assert resp.status_code == 500
    assert "GITHUB_TOKEN" in resp.json()["detail"]


def test_network_error_maps_to_502(client, monkeypatch):
    """A transport-level error (timeout, connect failure) is transient —
    returning 502 lets callers distinguish it from a real 404."""
    from app import main as main_mod

    async def fake_profile_timeout(username, token):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(main_mod, "get_user_profile", fake_profile_timeout)
    async def never(username, token):
        raise AssertionError
    monkeypatch.setattr(main_mod, "get_repos", never)

    resp = client.get("/api/profile/alice")
    assert resp.status_code == 502
