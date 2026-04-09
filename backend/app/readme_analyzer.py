import json
import re
import textstat
from openai import OpenAI
from .config import settings
from .prompts import README_ANALYSIS_PROMPT

_client = OpenAI(api_key=settings.openai_api_key)


async def analyze_readme(content: str) -> dict:
    """
    Analyze README content using OpenAI and return a dict with
    'summary', 'suggestions', 'readability_score', and 'missing_sections'.
    """
    messages = [
        {"role": "system", "content": README_ANALYSIS_PROMPT},
        {"role": "user", "content": content}
    ]
    response = _client.chat.completions.create(
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
