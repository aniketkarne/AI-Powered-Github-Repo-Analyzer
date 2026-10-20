"""
Pytest config for AI-Powered-Github-Repo-Analyzer backend.

The repo's ``app.readme_analyzer`` module instantiates an OpenAI client at
import time. Recent ``openai>=1.0`` raises when no key is provided, so the
test suite cannot import the app without a dummy value. We set a harmless
test-only key here; tests that exercise analyze_readme must monkey-patch
the module-level function rather than rely on a live OpenAI call.

We also auto-reset ``app.main._cache`` between tests so the in-memory cache
can't leak an HTTP error across test cases.
"""

import os

# Set a non-empty key BEFORE importing the app, so module import succeeds.
# Real OpenAI calls are intercepted by monkeypatch in each test.
os.environ.setdefault("OPENAI_API_KEY", "test-not-a-real-key")
os.environ.setdefault("GITHUB_TOKEN", "")


import pytest


@pytest.fixture(autouse=True)
def _reset_main_cache():
    """Wipe the module-level _cache in app.main before each test.

    app.main's cache_get/cache_set lives at module scope. Without this
    autouse fixture, tests run in alphabetical order and an earlier test
    may cache an HTTP error that a later test would inherit.
    """
    try:
        from app import main as main_mod
        main_mod._cache.clear()
    except ImportError:
        pass
    yield
    try:
        from app import main as main_mod
        main_mod._cache.clear()
    except ImportError:
        pass
