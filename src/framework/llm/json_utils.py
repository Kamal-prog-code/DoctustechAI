from __future__ import annotations

import ast
import json
import re
from typing import Any


def strip_code_fence(text: str) -> str:
    match = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def sanitize_json_text(text: str) -> str:
    text = text.replace("\u201c", "\"").replace("\u201d", "\"")
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = re.sub(r"\bNULL\b", "null", text, flags=re.IGNORECASE)
    text = re.sub(r"\bNONE\b", "null", text, flags=re.IGNORECASE)
    text = re.sub(r"\bN/A\b", "null", text, flags=re.IGNORECASE)
    text = re.sub(r",\s*([}\]])", r"\1", text)
    text = re.sub(
        r"([{\[,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:",
        r"\1\"\2\":",
        text,
    )
    return text


def parse_json_like(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        pass
    cleaned = sanitize_json_text(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    try:
        return ast.literal_eval(cleaned)
    except (ValueError, SyntaxError):
        return None


def iter_json_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    for open_char, close_char in (("{", "}"), ("[", "]")):
        depth = 0
        start = None
        for idx, char in enumerate(text):
            if char == open_char:
                if depth == 0:
                    start = idx
                depth += 1
            elif char == close_char and depth:
                depth -= 1
                if depth == 0 and start is not None:
                    candidates.append(text[start : idx + 1])
                    start = None
    return candidates
