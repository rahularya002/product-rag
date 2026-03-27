from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple


BASE_DIR = Path(__file__).resolve().parent
KNOWLEDGE_DIR = BASE_DIR / "knowledge"

API_BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")

# Voices used by the frontend
VOICE_HI_FEMALE = os.environ.get("VOICE_HI_FEMALE", "hi-IN-SwaraNeural")
VOICE_HI_MALE = os.environ.get("VOICE_HI_MALE", "hi-IN-MadhurNeural")
VOICE_EN_FEMALE = os.environ.get("VOICE_EN_FEMALE", "en-US-AriaNeural")


def http_post_json(url: str, payload: Dict[str, Any], timeout_s: int = 60) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        raise RuntimeError(f"HTTP {e.code} from {url}: {body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Failed to reach API at {API_BASE_URL}. Is backend running? ({e})") from e


def ask(question: str, voice: str, history: List[str] | None = None) -> str:
    res = http_post_json(
        f"{API_BASE_URL}/ask",
        {"question": question, "voice": voice, "history": history or []},
        timeout_s=120,
    )
    ans = res.get("answer")
    if not isinstance(ans, str):
        raise RuntimeError(f"Unexpected /ask response shape: {res}")
    return ans


def load_bullets(md_path: Path) -> List[str]:
    """
    Extract bullet items like:
      • Something
    """
    text = md_path.read_text(encoding="utf-8")
    bullets: List[str] = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("•"):
            item = line.lstrip("•").strip()
            if item:
                bullets.append(item)
    return bullets


_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")
_PUNCT_SPACE_RE = re.compile(r"([.!?])([A-Za-z])")


def sentence_count(s: str) -> int:
    # Treat both Western and Hindi danda as sentence boundaries
    parts = re.split(r"[.!?\u0964]+", s.strip())
    return sum(1 for p in parts if p.strip())


def violations_common(answer: str) -> List[str]:
    v: List[str] = []
    if "aapko kuch pata nahi" in answer.lower():
        v.append("insults/assumptions_about_user_knowledge")
    if "i am just an ai" in answer.lower() or "main sirf ai" in answer.lower():
        v.append("says_just_ai")
    if _PUNCT_SPACE_RE.search(answer):
        v.append("missing_space_after_punctuation")
    return v


def violations_hinglish(answer: str) -> List[str]:
    v = violations_common(answer)
    if _DEVANAGARI_RE.search(answer):
        v.append("contains_devanagari")
    return v


@dataclass
class TestCase:
    name: str
    voice: str
    question: str
    history: List[str] | None = None
    # (ok, message)
    validator: Any = None


def expect_contains_any(needles: List[str], min_hits: int = 2):
    needles_l = [n.lower() for n in needles]

    def _validate(answer: str) -> Tuple[bool, str]:
        a = answer.lower()
        hits = [n for n in needles_l if n and n in a]
        if len(set(hits)) >= min_hits:
            return True, f"ok ({len(set(hits))} hits)"
        return False, f"expected >= {min_hits} of: {needles[:8]} (hits={len(set(hits))})"

    return _validate


def expect_short_greeting(max_sentences: int = 2):
    def _validate(answer: str) -> Tuple[bool, str]:
        sc = sentence_count(answer)
        bad = violations_hinglish(answer)
        if sc <= max_sentences and not bad:
            return True, "ok"
        msg = f"sentences={sc} (max {max_sentences})"
        if bad:
            msg += f", violations={bad}"
        return False, msg

    return _validate


def expect_no_greeting_prefix():
    def _validate(answer: str) -> Tuple[bool, str]:
        a = answer.strip().lower()
        bad = violations_hinglish(answer)
        starts_with_namaste = a.startswith("namaste")
        if (not starts_with_namaste) and not bad:
            return True, "ok"
        msg = []
        if starts_with_namaste:
            msg.append("starts_with_namaste")
        if bad:
            msg.append(f"violations={bad}")
        return False, ", ".join(msg) or "failed"

    return _validate


def main() -> int:
    if not KNOWLEDGE_DIR.exists():
        print(f"ERROR: knowledge dir not found at {KNOWLEDGE_DIR}")
        return 2

    # Build expectations from knowledge
    hi_categories = load_bullets(KNOWLEDGE_DIR / "hi" / "03_product_categories.md")
    hi_crafts = load_bullets(KNOWLEDGE_DIR / "hi" / "04_crafts_and_artisans.md")

    tests: List[TestCase] = [
        TestCase(
            name="hi_greeting_short",
            voice=VOICE_HI_FEMALE,
            question="namaste",
            validator=expect_short_greeting(max_sentences=2),
        ),
        TestCase(
            name="hi_no_repeat_greeting_on_question",
            voice=VOICE_HI_FEMALE,
            question="ji hai, kya aap mujhe rajasthali ke baare mein kuch bata sakti ho?",
            history=["USER: namaste", "ASSISTANT: Namaste! Main Rajasthali ki AI assistant hoon. Main aapki kaise madad kar sakti hoon?"],
            validator=expect_no_greeting_prefix(),
        ),
        TestCase(
            name="hi_categories_grounded",
            voice=VOICE_HI_FEMALE,
            question="Aapke paas kaun kaun si product categories milti hain? 4-5 examples de dijiye.",
            validator=expect_contains_any(hi_categories, min_hits=2),
        ),
        TestCase(
            name="hi_crafts_grounded",
            voice=VOICE_HI_FEMALE,
            question="Rajasthali kin traditional crafts mein specialize karta hai? 3-4 examples bol dijiye.",
            validator=expect_contains_any(hi_crafts, min_hits=2),
        ),
        TestCase(
            name="en_missing_policy_safe_answer",
            voice=VOICE_EN_FEMALE,
            question="What is your exact return window in days? Reply with the exact number only.",
            validator=lambda a: (
                ("don't know" in a.lower() or "not specified" in a.lower() or "may not be available" in a.lower()),
                "should refuse when not in context",
            ),
        ),
    ]

    print(f"API: {API_BASE_URL}")
    print(f"Running {len(tests)} tests...\n")

    passed = 0
    start = time.time()
    for t in tests:
        try:
            ans = ask(t.question, t.voice, t.history)
        except Exception as e:
            print(f"[FAIL] {t.name}: request error: {e}")
            continue

        ok, msg = (True, "ok")
        if t.validator:
            ok, msg = t.validator(ans)

        if ok:
            passed += 1
            print(f"[PASS] {t.name}: {msg}")
        else:
            print(f"[FAIL] {t.name}: {msg}")
            print("  question:", t.question)
            preview = ans.replace("\n", " ").strip()
            if len(preview) > 240:
                preview = preview[:240] + "…"
            print("  answer:  ", preview)

    elapsed = time.time() - start
    print(f"\nDone. Passed {passed}/{len(tests)} in {elapsed:.1f}s")
    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    raise SystemExit(main())

