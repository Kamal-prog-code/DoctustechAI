import re


ASSESSMENT_HEADER_RE = re.compile(r"assessment\s*/\s*plan", re.IGNORECASE)
STOP_HEADER_RE = re.compile(
    r"^\s*(return to office|encounter sign[- ]?off|encounter sign off)\b",
    re.IGNORECASE | re.MULTILINE,
)


def extract_assessment_plan(note_text: str) -> str:
    match = ASSESSMENT_HEADER_RE.search(note_text)
    if not match:
        return ""

    remainder = note_text[match.end() :].lstrip(" :\n\r\t")
    stop_match = STOP_HEADER_RE.search(remainder)
    if stop_match:
        remainder = remainder[: stop_match.start()]
    return remainder.strip()


def normalize_icd10_code(code: str | None) -> str:
    if not code:
        return ""
    return re.sub(r"[^A-Za-z0-9]", "", code).upper()


def normalize_description(text: str | None) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9]+", " ", text.lower())
    return " ".join(cleaned.split())
