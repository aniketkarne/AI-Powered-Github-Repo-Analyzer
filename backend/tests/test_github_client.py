"""Tests for github_client.

We never hit the live GitHub API in tests. Instead we patch
``httpx.AsyncClient`` so every request goes through an ``httpx.MockTransport``
that the test controls. This pins behavior across:
  - pagination bounds (repos loop must stop, must cap at max_repos)
  - ``type=owner`` is forwarded so private repos don't leak
  - the GITHUB_TOKEN is forwarded when present
  - ``Accept: application/vnd.github.v3.raw`` is set on README fetches
  - error paths surface httpx.HTTPStatusError so callers can handle them
"""
from typing import Any, Callable, Dict, List, Tuple

import httpx
import pytest

from app import github_client


class _TransportRecorder:
    """Records every request URL + params and serves a programmable response."""

    def __init__(self) -> None:
        self.requests: List[Tuple[str, Dict[str, Any], Dict[str, str]]] = []

    def page_handler(
        self, page_responses: List[List[Dict[str, Any]]]
    ) -> Callable[[httpx.Request], httpx.Response]:
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(
                (str(request.url), dict(request.url.params), dict(request.headers))
            )
            params = dict(request.url.params)
            page = int(params.get("page", 1))
            if page - 1 < len(page_responses):
                return httpx.Response(200, json=page_responses[page - 1])
            return httpx.Response(200, json=[])

        return handler

    def json_handler(
        self, body: Tuple[int, Dict[str, Any]]
    ) -> Callable[[httpx.Request], httpx.Response]:
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(
                (str(request.url), dict(request.url.params), dict(request.headers))
            )
            status, payload = body
            return httpx.Response(status, json=payload)

        return handler

    def text_handler(
        self, body: Tuple[int, str]
    ) -> Callable[[httpx.Request], httpx.Response]:
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(
                (str(request.url), dict(request.url.params), dict(request.headers))
            )
            status, text = body
            return httpx.Response(
                status, text=text, headers={"content-type": "text/plain"}
            )

        return handler


def _patch_async_client(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> None:
    """Replace ``httpx.AsyncClient`` for the duration of the test.

    github_client constructs ``httpx.AsyncClient()`` directly, so we need
    to swap in a stand-in class. The stand-in must NOT call
    ``httpx.AsyncClient(...)`` itself — that would recurse into the
    patched attribute — so it grabs a direct reference to the real class
    before the monkeypatch is installed.
    """
    real_async_client = httpx.AsyncClient

    class _FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._transport = httpx.MockTransport(handler)
            self._client = real_async_client(transport=self._transport)

        async def __aenter__(self) -> httpx.AsyncClient:
            return self._client

        async def __aexit__(self, *exc: Any) -> None:
            await self._client.aclose()

    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)


def _make_repo(name: str, *, stars: int = 0, language: str = "Python") -> Dict[str, Any]:
    return {
        "name": name,
        "description": f"{name} desc",
        "stargazers_count": stars,
        "forks_count": 0,
        "language": language,
        "pushed_at": "2026-01-01T00:00:00Z",
    }


@pytest.mark.asyncio
async def test_get_repos_paginates_until_short_page(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _TransportRecorder()
    # 3 pages of 100/100/50 — last is < per_page so the loop exits.
    pages = [
        [_make_repo(f"r{i}") for i in range(100)],
        [_make_repo(f"r{i}") for i in range(100, 200)],
        [_make_repo(f"r{i}") for i in range(200, 250)],
    ]
    _patch_async_client(monkeypatch, recorder.page_handler(pages))

    repos = await github_client.get_repos("octocat", token="")

    assert len(repos) == 250
    assert [r["name"] for r in repos[:3]] == ["r0", "r1", "r2"]
    assert [r["name"] for r in repos[-3:]] == ["r247", "r248", "r249"]
    # Paged through with sort=pushed and type=owner on every request.
    assert len(recorder.requests) == 3
    for _url, params, _headers in recorder.requests:
        assert params["per_page"] == "100"
        assert params["sort"] == "pushed"
        assert params["type"] == "owner"


@pytest.mark.asyncio
async def test_get_repos_caps_at_max_repos(monkeypatch: pytest.MonkeyPatch) -> None:
    """A user with thousands of repos must not produce a runaway loop.

    Cap the loop so the worst case is bounded. We simulate 10 full pages
    and assert get_repos stops after the cap is hit.
    """
    recorder = _TransportRecorder()
    pages = [
        [_make_repo(f"r{i}") for i in range(start, start + 100)]
        for start in range(0, 1000, 100)
    ]
    _patch_async_client(monkeypatch, recorder.page_handler(pages))

    repos = await github_client.get_repos("prolific", token="", max_repos=300)

    assert len(repos) == 300
    # 300/100 = 3 pages requested (4th would push us past the cap, loop breaks).
    assert len(recorder.requests) == 3


@pytest.mark.asyncio
async def test_get_repos_forwards_type_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default ``type=owner`` prevents the analyzer from leaking private repos
    that an accidentally-pasted GITHUB_TOKEN can see.
    """
    recorder = _TransportRecorder()
    pages = [[_make_repo("hello")]]
    _patch_async_client(monkeypatch, recorder.page_handler(pages))

    await github_client.get_repos("octocat", token="")

    _url, params, _headers = recorder.requests[0]
    assert params["type"] == "owner"


@pytest.mark.asyncio
async def test_get_repos_forwards_token_when_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _TransportRecorder()
    pages = [[_make_repo("hello")]]
    _patch_async_client(monkeypatch, recorder.page_handler(pages))

    await github_client.get_repos("octocat", token="ghp_test")

    _url, _params, headers = recorder.requests[0]
    # httpx normalizes header names to lowercase on read.
    assert headers.get("authorization") == "token ghp_test"


@pytest.mark.asyncio
async def test_get_repos_no_auth_header_when_token_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _TransportRecorder()
    pages = [[_make_repo("hello")]]
    _patch_async_client(monkeypatch, recorder.page_handler(pages))

    await github_client.get_repos("octocat", token="")

    _url, _params, headers = recorder.requests[0]
    assert "authorization" not in headers


@pytest.mark.asyncio
async def test_get_repos_returns_slim_dict_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lock in the per-repo shape returned to callers.

    The frontend reads exactly these (name, description, stars, forks,
    language, pushed_at). Larger fields from the GitHub response would
    inflate payloads and risk leaking private metadata.
    """
    recorder = _TransportRecorder()
    full_repo = {
        "name": "big",
        "description": "x",
        "stargazers_count": 42,
        "forks_count": 7,
        "language": "Go",
        "pushed_at": "2026-09-01T00:00:00Z",
        # Fields the analyzer must DROP — large, noisy, and may be private.
        "id": 12345,
        "node_id": "R_kgDONODE",
        "full_name": "octocat/big",
        "html_url": "https://github.com/octocat/big",
        "owner": {"login": "octocat"},
        "private": True,
        "topics": ["x"],
        "default_branch": "main",
        "visibility": "private",
    }
    pages = [[full_repo]]
    _patch_async_client(monkeypatch, recorder.page_handler(pages))

    repos = await github_client.get_repos("octocat", token="")
    assert len(repos) == 1
    repo = repos[0]
    assert repo == {
        "name": "big",
        "description": "x",
        "stars": 42,
        "forks": 7,
        "language": "Go",
        "pushed_at": "2026-09-01T00:00:00Z",
    }


@pytest.mark.asyncio
async def test_get_repos_propagates_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    _patch_async_client(monkeypatch, handler)

    with pytest.raises(httpx.HTTPStatusError):
        await github_client.get_repos("nonexistent-user-xyz", token="")


@pytest.mark.asyncio
async def test_get_user_profile_returns_profile_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _TransportRecorder()
    body = (200, {"login": "octocat", "name": "The Octocat", "public_repos": 8})
    _patch_async_client(monkeypatch, recorder.json_handler(body))

    profile = await github_client.get_user_profile("octocat", token="")
    assert profile == {"login": "octocat", "name": "The Octocat", "public_repos": 8}


@pytest.mark.asyncio
async def test_get_readme_uses_raw_accept_header(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _TransportRecorder()
    body = (200, "# hello\n")
    _patch_async_client(monkeypatch, recorder.text_handler(body))

    text = await github_client.get_readme("octocat", "hello", token="ghp_test")
    assert text == "# hello\n"
    _url, _params, headers = recorder.requests[0]
    # httpx normalizes header names to lowercase on read.
    assert headers.get("accept") == "application/vnd.github.v3.raw"
    assert headers.get("authorization") == "token ghp_test"


@pytest.mark.asyncio
async def test_get_readme_propagates_404(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    _patch_async_client(monkeypatch, handler)

    with pytest.raises(httpx.HTTPStatusError):
        await github_client.get_readme("octocat", "no-readme", token="ghp_test")