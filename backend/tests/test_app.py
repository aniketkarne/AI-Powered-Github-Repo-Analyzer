"""Smoke tests for the FastAPI app — health endpoint, CORS middleware shape."""
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_returns_ok():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_cors_does_not_advertise_credentials_with_wildcard_origin():
    """allow_credentials=True with allow_origins=['*'] is dead — browsers
    drop the credentials anyway. Pin the behavior so a future change
    doesn't reintroduce the silent bug.

    We introspect Starlette's Middleware records via getattr because
    user_middleware is an internal collection and the wrapper shape
    (Middleware vs _MiddlewareFactory) is not part of the public API.
    """
    found_cors = False
    for mw in app.user_middleware:
        wrapped = getattr(mw, "cls", None)
        underlying = getattr(wrapped, "cls", wrapped)
        if getattr(underlying, "__name__", "") == "CORSMiddleware":
            found_cors = True
            opts = getattr(mw, "kwargs", {})
            assert opts.get("allow_origins") == ["*"], opts
            assert opts.get("allow_credentials") is False, opts
            break
    assert found_cors, "CORSMiddleware not registered on the app"