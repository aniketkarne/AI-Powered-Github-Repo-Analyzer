from typing import Any, Dict

README_ANALYSIS_PROMPT = """
You are a professional GitHub reviewer. Given the content of a repository's README, provide:
1. A concise summary.
2. Suggestions to improve documentation including missing sections, clarity, examples, etc.
Respond as JSON with keys "summary" and "suggestions".
"""

KEYWORD_EXTRACTION_PROMPT = """
You are an assistant. Given the text of a README, extract the top 5 most relevant keywords or topics. Respond as JSON with key "keywords" containing a list of strings.
"""