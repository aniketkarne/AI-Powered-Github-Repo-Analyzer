import json
import openai
import re
import textstat
from .config import settings
from .prompts import README_ANALYSIS_PROMPT

async def analyze_readme(content: str) -> dict:
    """
    Analyze README content using OpenAI and return a dict with 'summary' and 'suggestions'.
    """
    openai.api_key = settings.openai_api_key
    messages = [
        {"role": "system", "content": README_ANALYSIS_PROMPT},
        {"role": "user", "content": content}
    ]
    response = await openai.ChatCompletion.acreate(
        model="4o-mini",
        messages=messages,
        temperature=0.2
    )
    # Extract the JSON response
    text = response.choices[0].message.content
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        # Fallback if response is not valid JSON
        result = {"summary": text, "suggestions": []}

    # Add readability score
    result["readability_score"] = textstat.flesch_kincaid_grade(content)

    # Check for missing sections
    required_sections = ["Installation", "Usage", "License", "Contributing"]
    missing = []
    for sec in required_sections:
        if not re.search(rf'^#+\s*{sec}', content, re.MULTILINE):
            missing.append(sec)
    result["missing_sections"] = missing

    return result