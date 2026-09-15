# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- `analyze_readme` was calling the sync OpenAI client from inside an `async def`
  function. Every concurrent `/readme-report` request now serializes behind the
  previous OpenAI round-trip. Switched to `AsyncOpenAI` so LLM calls no longer
  block the event loop.
- CORS middleware was setting `allow_credentials=True` alongside `allow_origins=["*"]`,
  which browsers silently refuse (credentialed requests with a wildcard origin
  are dropped). CORS now advertises `allow_credentials=False`; flip it to `True`
  and scope `allow_origins` only when real authentication is added.

### Added
- `LICENSE` (MIT) — the README claimed MIT but the file was missing.
- `backend/.dockerignore` — keeps `venv/`, `__pycache__/`, `.env`, and build
  artefacts out of the Docker build context.
- `frontend/.gitignore` — covers `node_modules/`, build output, env files,
  and editor caches that the repo-level `.gitignore` was missing.
- `backend/tests/` — pytest smoke suite for the missing-sections detector,
  the async OpenAI call shape, the JSON-parse fallback, and the CORS
  middleware configuration.
- `.github/workflows/tests.yml` — runs the backend pytest suite on Python 3.10
  and 3.11 for every push and PR.

### Changed
- `backend/Dockerfile` — `FROM python:3.11-slim` → `python:3.11-slim-bookworm`
  so the base image is pinned to a named Debian release instead of drifting.
- `README.md` — replaced `your-org/your-repo` placeholder clone URL with the
  real repo path; dropped claims of `aioredis` / `REDIS_URL` (not in the
  dependency list, not used in code); corrected the model name from
  `GPT-3.5-turbo` to `gpt-4o-mini` (matches `backend/app/readme_analyzer.py`);
  added a "Running Tests" section and a CI badge.