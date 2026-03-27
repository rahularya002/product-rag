from __future__ import annotations

import re
from typing import List

from .prompts import is_hindi_voice


_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]+")


def remove_devanagari(text: str) -> str:
    """Strip any Devanagari characters the model accidentally emits."""
    return _DEVANAGARI_RE.sub("", text).strip()


_LEADING_GREETING_RE = re.compile(
    r"^\s*(?:namaste|namste|namaskar|pranam|hi|hello|hey|"
    r"aapka\s+swagat\s+hai|rajasthali\s+mein\s+aapka\s+swagat\s+hai)"
    r"\b[\s,!\.\-]*",
    flags=re.IGNORECASE,
)


def strip_leading_greeting(text: str) -> str:
    if not text:
        return text
    stripped = _LEADING_GREETING_RE.sub("", text, count=1).lstrip()
    return stripped or text


_META_TRAIL_RE = re.compile(
    r"""
    (?:\s*[\(\[\{]?\s*)
    (?:changes?|edit(?:ed)?|fixed|note|notes)\s*:
    [^\)\]\}]*
    (?:[\)\]\}]?\s*)$
    """,
    flags=re.IGNORECASE | re.VERBOSE,
)


def strip_meta_notes(text: str) -> str:
    if not text:
        return text
    out = text.strip()
    out2 = _META_TRAIL_RE.sub("", out).strip()
    return out2 or out


_MALE_MARKERS = [
    "kar sakta hoon",
    "kar sakta hun",
    "batata hoon",
    "batata hun",
    "bataunga",
    "kar sakta",
    "ban gaya hoon",
    "ban chuka hoon",
]

_FEMALE_MARKERS = [
    "kar sakti hoon",
    "kar sakti hun",
    "batati hoon",
    "batati hun",
    "bataungi",
    "kar sakti",
    "ban gayi hoon",
    "ban chuki hoon",
]


def _hinglish_spelling_fixes(text: str, voice: str) -> str:
    """
    Small deterministic fixes to improve Hinglish naturalness.

    Keep this conservative: only fix known awkward phrases/typos.
    """
    if not text or not is_hindi_voice(voice):
        return text

    out = text

    # Common awkward/over-formal phrasing produced by some models.
    out = out.replace("jaankari pradaan kar sakti hoon", "jaankari de sakti hoon")
    out = out.replace("jaankari pradaan kar sakta hoon", "jaankari de sakta hoon")

    # Typos seen in the wild.
    # Only fix standalone typo "aditional" (avoid touching words like "traditional").
    out = re.sub(r"\baditional\b", "additional", out, flags=re.IGNORECASE)

    return out


def _contains_any(text: str, needles: List[str]) -> bool:
    t = (text or "").lower()
    return any(n in t for n in needles)


def has_gender_violation(answer: str, voice: str) -> bool:
    if not is_hindi_voice(voice):
        return False

    v = (voice or "").lower()
    is_female = "swara" in v  # Hindi female voice

    if is_female:
        return _contains_any(answer, _MALE_MARKERS)
    return _contains_any(answer, _FEMALE_MARKERS)


def rewrite_with_correct_gender(answer: str, voice: str, grammar_llm) -> str:
    """
    Targeted grammar rewrite using grammar_llm (temp=0.0).
    Only fixes gender markers — preserves factual content.
    """
    if not is_hindi_voice(voice):
        return answer

    v = (voice or "").lower()
    is_female = "swara" in v
    gender = "FEMALE" if is_female else "MALE"

    must_use = (
        "kar sakti hoon / batati hoon / bataungi" if is_female else "kar sakta hoon / batata hoon / bataunga"
    )
    must_avoid = (
        "kar sakta hoon / batata hoon / bataunga" if is_female else "kar sakti hoon / batati hoon / bataungi"
    )

    rewrite_prompt = f"""Fix ONLY the gender grammar in the Hinglish text below.

Rules:
- Gender: {gender}
- Use: {must_use}
- Avoid: {must_avoid}
- Do NOT change any factual content, product names, or sentences unrelated to gender.
- Do NOT add greetings.
- Output ONLY the corrected text, nothing else.
- Use Roman script only (no Devanagari).

Text:
{answer}"""

    try:
        result = grammar_llm.invoke(rewrite_prompt)
        return result.strip()
    except Exception:
        return answer


def post_process(text: str, voice: str, grammar_llm, is_greeting_response: bool = False) -> str:
    """
    Full post-processing pipeline:
    1. Remove stray Devanagari (Hindi voices only)
    2. Strip leading greeting (if not a greeting response)
    3. Fix gender violations
    4. Strip meta notes
    """
    out = text or ""

    if is_hindi_voice(voice):
        out = remove_devanagari(out)

    if not is_greeting_response:
        out = strip_leading_greeting(out)

    if has_gender_violation(out, voice):
        out = rewrite_with_correct_gender(out, voice, grammar_llm)
        out = strip_leading_greeting(out)  # model may re-add greeting in rewrite

    out = _hinglish_spelling_fixes(out, voice)
    out = strip_meta_notes(out)
    return out.strip()

