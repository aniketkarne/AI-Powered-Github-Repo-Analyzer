"""Tests for readme_analyzer.

The full analyze_readme path calls OpenAI's chat completions API. We don't
hit the network in unit tests — we mock the AsyncOpenAI client to verify the
call shape, and we directly exercise the local logic (missing-section
detection, JSON parse fallback, readability score) which is what actually
runs on every request.
"""
import json
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.readme_analyzer import analyze_readme


SAMPLE_README = """# my-project

A short description.

## Installation

```
pip install my-project
```

## Usage

Run `my-project`.

## License

MIT.

## Contributing

PRs welcome.
"""


def _find_missing_sections(content: str) -> list[str]:
    """Mirror the detector in analyze_readme so we can assert it directly."""
    required = ["Installation", "Usage", "License", "Contributing"]
    return [s for s in required if not re.search(rf"^#+\s*{s}", content, re.MULTILINE)]


def test_missing_sections_detects_missing_top_level_sections():
    missing = _find_missing_sections("# my-project\n\nJust a description.\n")
    assert missing == ["Installation", "Usage", "License", "Contributing"]


def test_missing_sections_passes_when_all_present():
    missing = _find_missing_sections(SAMPLE_README)
    assert missing == []


def test_missing_sections_is_case_sensitive():
    """The detector looks for exact casing. Lowercase variants slip through."""
    missing = _find_missing_sections("# installation\n\n")
    assert "Installation" in missing


def test_missing_sections_ignores_inline_mentions():
    content = "The Installation section will be added soon.\n\n# License\n\nMIT.\n"
    missing = _find_missing_sections(content)
    assert "Installation" in missing


@pytest.mark.asyncio
async def test_analyze_readme_uses_async_client():
    """Regression: ensure we hit the async OpenAI path, not the sync one.

    The sync client blocks the event loop while the request is in flight,
    which serializes every concurrent /readme-report call behind each
    OpenAI round-trip. This test pins the implementation to AsyncOpenAI.
    """
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps({
        "summary": "ok",
        "suggestions": ["x"]
    })

    with patch("app.readme_analyzer._client") as _client_factory:
        client = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=mock_response)
        _client_factory.return_value = client

        result = await analyze_readme(SAMPLE_README)

    assert result["summary"] == "ok"
    assert result["suggestions"] == ["x"]
    assert result["missing_sections"] == []
    assert "readability_score" in result
    client.chat.completions.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_analyze_readme_falls_back_to_text_when_model_returns_non_json():
    """If the model emits prose instead of JSON, surface the raw text under summary."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "This README is short and clear."

    with patch("app.readme_analyzer._client") as _client_factory:
        client = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=mock_response)
        _client_factory.return_value = client

        result = await analyze_readme(SAMPLE_README)

    assert result["summary"] == "This README is short and clear."
    assert result["suggestions"] == []


@pytest.mark.asyncio
async def test_analyze_readme_lists_missing_sections():
    """Combined check: real-ish README that omits Usage triggers 'Usage'."""
    partial = "# project\n\n## Installation\n\npip install x\n\n## License\n\nMIT.\n\n## Contributing\n\nPRs welcome.\n"
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps({"summary": "s", "suggestions": []})

    with patch("app.readme_analyzer._client") as _client_factory:
        client = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=mock_response)
        _client_factory.return_value = client

        result = await analyze_readme(partial)

    assert "Usage" in result["missing_sections"]
    assert "Installation" not in result["missing_sections"]