import json
import re
import textstat
from openai import AsyncOpenAI
from .config import settings
from .prompts import README_ANALYSIS_PROMPT


def _client() -> AsyncOpenAI:
    # Lazy: server can start without OPENAI_API_KEY; only callers that hit
    # analyze_readme need a key, and the SDK raises AuthenticationError on
    # the actual request, not at import.
    return AsyncOpenAI(api_key=settings.openai_api_key)


async def analyze_readme(content: str) -> dict:
    """
    Analyze README content using OpenAI and return a dict with
    'summary', 'suggestions', 'readability_score', and 'missing_sections'.
    """
    messages = [
        {"role": "system", "content": README_ANALYSIS_PROMPT},
        {"role": "user", "content": content}
    ]
    response = await _client().chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.2
    )
    text = response.choices[0].message.content
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        result = {"summary": text, "suggestions": []}

    result["readability_score"] = textstat.flesch_kincaid_grade(content)

    required_sections = ["Installation", "Usage", "License", "Contributing"]
    missing = []
    for sec in required_sections:
        if not re.search(rf'^#+\s*{sec}', content, re.MULTILINE):
            missing.append(sec)
    result["missing_sections"] = missing

    return result