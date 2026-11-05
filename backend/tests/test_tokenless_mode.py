"""Regression tests for the token-less deployment path.

Running without GITHUB_TOKEN / OPENAI_API_KEY is a supported config (the
README lists both as optional .env values). Two things silently broke it:

1. ``get_readme`` always sent ``Authorization: token `` — an empty
   credential — which GitHub rejects with 401 even for public repos.
   Profile and repo listings guarded against this; README fetch did not,
   so /api/profile/{username}/readme-report returned ``{"reports": []}``
   with no error on any token-less deployment.
2. ``config.Settings`` loaded ``.env`` relative to the process cwd, so
   launching uvicorn from anywhere other than backend/ dropped both
   tokens silently.

No conftest.py on purpose — this file must run standalone under plain
``pytest`` regardless of which other test modules are present.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import pytest

from app import github_client
from app import config as app_config
from app.config import DEFAULT_ENV_FILE, Settings, build_settings


def _capture_requests(monkeypatch, response_factory=None):
    """Route github_client's HTTP calls into a MockTransport.

    Returns a dict capturing the Authorization header of the last request.
    """
    seen = {}

    def default_response(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/readme"):
            return httpx.Response(200, content=b"# readme body")
        if request.url.path.endswith("/repos"):
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={"login": "octocat"})

    handler = response_factory or default_response
    real_async_client = httpx.AsyncClient

    def handler_wrapper(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization")
        seen["accept"] = request.headers.get("accept")
        return handler(request)

    transport = httpx.MockTransport(handler_wrapper)

    def capture(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(github_client.httpx, "AsyncClient", capture)
    return seen


def test_get_readme_without_token_sends_no_authorization(monkeypatch):
    seen = _capture_requests(monkeypatch)
    body = asyncio.run(github_client.get_readme("octocat", "hello-world", ""))
    assert body == "# readme body"
    assert seen["authorization"] is None, (
        "empty token must not produce an Authorization header — GitHub "
        "rejects the empty credential with 401 even for public repos"
    )
    assert seen["accept"] == "application/vnd.github.v3.raw"


def test_get_readme_with_token_sends_authorization(monkeypatch):
    seen = _capture_requests(monkeypatch)
    asyncio.run(github_client.get_readme("octocat", "hello-world", "abc123"))
    assert seen["authorization"] == "token abc123"


def test_profile_and_repos_without_token_send_no_authorization(monkeypatch):
    seen = _capture_requests(monkeypatch)
    profile = asyncio.run(github_client.get_user_profile("octocat", ""))
    assert profile == {"login": "octocat"}
    assert seen["authorization"] is None

    repos = asyncio.run(github_client.get_repos("octocat", ""))
    assert repos == []
    assert seen["authorization"] is None


def test_default_env_file_is_package_anchored():
    expected = Path(app_config.__file__).resolve().parent.parent / ".env"
    assert DEFAULT_ENV_FILE == expected
    assert DEFAULT_ENV_FILE.is_absolute()


def test_default_env_file_is_cwd_independent(tmp_path, monkeypatch):
    before = DEFAULT_ENV_FILE
    monkeypatch.chdir(tmp_path)
    assert DEFAULT_ENV_FILE == before
    # build_settings() must still resolve to the package-anchored file
    settings = build_settings()
    assert settings.model_config.get("env_file") in (before, str(before))


def test_build_settings_reads_env_file_from_any_cwd(tmp_path, monkeypatch):
    env_file = tmp_path / "alt.env"
    env_file.write_text("GITHUB_TOKEN=ghp_from_file\nOPENAI_API_KEY=sk-from-file\n")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = build_settings(env_file)
    assert settings.github_token == "ghp_from_file"
    assert settings.openai_api_key == "sk-from-file"


def test_real_env_vars_beat_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / "alt.env"
    env_file.write_text("GITHUB_TOKEN=ghp_from_file\n")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_from_env")
    settings = build_settings(env_file)
    assert settings.github_token == "ghp_from_env"


def test_settings_default_to_empty_strings(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)  # no .env here
    settings = Settings(_env_file=None)
    assert settings.github_token == ""
    assert settings.openai_api_key == ""
