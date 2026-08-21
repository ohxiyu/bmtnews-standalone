"""Shared AI utility functions."""

import json
import re
from typing import Iterable, Optional


def parse_json_response(response: str) -> Optional[dict]:
    """Try multiple strategies to extract a JSON object from an AI response.

    Returns the parsed dict, or None if all strategies fail.
    """
    text = response.strip()

    # Strategy 1: direct parse
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    # Strategy 2: extract from ```json ... ``` code block
    if "```json" in text:
        try:
            json_str = text.split("```json")[1].split("```")[0].strip()
            return json.loads(json_str)
        except (json.JSONDecodeError, ValueError, IndexError):
            pass

    # Strategy 3: extract from ``` ... ``` code block
    if "```" in text:
        try:
            json_str = text.split("```")[1].split("```")[0].strip()
            return json.loads(json_str)
        except (json.JSONDecodeError, ValueError, IndexError):
            pass

    # Strategy 4: find the first { ... } block using brace matching
    start = text.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except (json.JSONDecodeError, ValueError):
                        break

    # Strategy 5: regex extraction as last resort
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except (json.JSONDecodeError, ValueError):
            pass

    return None


_FENCE = re.compile(r"^\s*```[a-zA-Z0-9_-]*\s*\n(.*?)\n?\s*```\s*$", re.DOTALL)


def _strip_code_fence(text: str) -> str:
    match = _FENCE.match(text)
    return match.group(1).strip() if match else text


def unwrap_prose_response(
    response: object,
    *,
    keys: Iterable[str] = (),
) -> str:
    """Return the prose a model was asked for, unwrapping JSON if it wrapped it.

    Most prompts in this pipeline ask for JSON, and models trained on that
    mix will occasionally answer a prose prompt with ``{"lede": "..."}``
    anyway. Rendering that verbatim puts raw JSON on the page, so every
    prose call is funnelled through here.

    ``keys`` names the fields worth unwrapping; a single-field object is
    unwrapped whatever the field is called, because a lone string value is
    unambiguously the answer.
    """
    text = _strip_code_fence(str(response or "").strip())
    if not text.startswith("{"):
        return text

    payload = parse_json_response(text)
    if not isinstance(payload, dict) or not payload:
        return text

    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    strings = [
        value.strip()
        for value in payload.values()
        if isinstance(value, str) and value.strip()
    ]
    if len(strings) == 1:
        return strings[0]
    return text
