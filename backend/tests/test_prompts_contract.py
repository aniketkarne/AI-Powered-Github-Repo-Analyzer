"""Contract tests for the LLM prompts.

Self-contained: inserts backend/ on sys.path so plain `pytest` works from a
bare clone with no conftest.py and no installed package.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.prompts import KEYWORD_EXTRACTION_PROMPT, README_ANALYSIS_PROMPT  # noqa: E402


def test_analysis_prompt_demands_raw_json_without_fences():
    # A fenced reply ("```json ... ```") breaks json.loads in analyze_readme
    # and the whole blob lands in the summary field. The prompt must forbid it.
    assert "raw JSON" in README_ANALYSIS_PROMPT
    assert "markdown code fences" in README_ANALYSIS_PROMPT
    assert "nothing else" in README_ANALYSIS_PROMPT


def test_analysis_prompt_pins_the_consumed_contract():
    # analyze_readme parses exactly these two keys; readability_score and
    # missing_sections are computed afterwards and must not be model output.
    assert '"summary"' in README_ANALYSIS_PROMPT
    assert '"suggestions"' in README_ANALYSIS_PROMPT
    assert "list of strings" in README_ANALYSIS_PROMPT


def test_keyword_prompt_declares_its_json_shape():
    assert '"keywords"' in KEYWORD_EXTRACTION_PROMPT
    assert "list of strings" in KEYWORD_EXTRACTION_PROMPT
