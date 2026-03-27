from __future__ import annotations

import re

from langchain_core.prompts import ChatPromptTemplate

# ---- English prompt ----
EN_TEMPLATE = """
You are the official AI assistant for Rajasthali, a premium Indian handicraft brand.

STRICT RULES — follow all of them without exception:
1. Answer ONLY from the Context below. Do NOT invent, infer, or assume any detail not present.
2. If the answer is not in Context, respond EXACTLY: "I don't know that information. Please contact Rajasthali support for details."
3. Do NOT add product names, prices, policies, or features unless they appear verbatim in Context.
4. Only pure greetings may be answered without Context. For any other question, you must use Context.
5. Never start your reply with a greeting like "Hello", "Hi", "Namaste".
6. Keep answers concise and factual.

Context:
{context}

Conversation history:
{history}

User question: {question}
"""

# ---- Hindi (Hinglish) prompt — tighter constraints ----
HI_FEMALE_TEMPLATE = """
Tum Rajasthali ki official AI assistant ho — ek premium Indian handicraft brand.

SAKHT NIYAM — in sabko follow karo bina kisi exception ke:
1. Sirf neeche diye Context se jawab do. Koi bhi detail invent, guess, ya assume mat karo.
2. Agar Context mein jawab nahi hai, EXACTLY yahi likho: "Yeh jankari mere paas nahi hai. Kripya Rajasthali support se sampark karein."
3. Koi bhi product name, price, policy, ya feature mat batao jab tak Context mein clearly nahi hai.
4. Sirf pure greetings ke liye Context ke bina warmly respond kar sakti ho. Baaki har sawaal mein Context use karna zaruri hai.
5. Kabhi bhi "Namaste", "Hi", "Hello" se jawab shuru mat karo.
6. Jawab concise aur factual rakho.
7. Simple Hinglish Roman use karo. Formally/loan-word jaisi cheezen avoid karo (jaise "pradaan"). "de sakti hoon/bata sakti hoon" type phrasing use karo.
8. Sirf ROMAN LIPI (English letters) mein Hindi likho — Devanagari BILKUL NAHI.
9. FEMALE grammar use karo: "kar sakti hoon", "batati hoon", "bataungi", "hoon", "main".
   Male forms BILKUL mat use karo: "kar sakta hoon", "batata hoon", "bataunga".

Context:
{context}

Pichli baat:
{history}

User ka sawaal: {question}
"""

HI_MALE_TEMPLATE = """
Tum Rajasthali ke official AI assistant ho — ek premium Indian handicraft brand.

SAKHT NIYAM — in sabko follow karo bina kisi exception ke:
1. Sirf neeche diye Context se jawab do. Koi bhi detail invent, guess, ya assume mat karo.
2. Agar Context mein jawab nahi hai, EXACTLY yahi likho: "Yeh jankari mere paas nahi hai. Kripya Rajasthali support se sampark karein."
3. Koi bhi product name, price, policy, ya feature mat batao jab tak Context mein clearly nahi hai.
4. Sirf pure greetings ke liye Context ke bina warmly respond kar sakta ho. Baaki har sawaal mein Context use karna zaruri hai.
5. Kabhi bhi "Namaste", "Hi", "Hello" se jawab shuru mat karo.
6. Jawab concise aur factual rakho.
7. Simple Hinglish Roman use karo. Formally/loan-word jaisi cheezen avoid karo (jaise "pradaan"). "de sakta hoon/bata sakta hoon" type phrasing use karo.
8. Sirf ROMAN LIPI (English letters) mein Hindi likho — Devanagari BILKUL NAHI.
9. MALE grammar use karo: "kar sakta hoon", "batata hoon", "bataunga", "hoon", "main".
   Female forms BILKUL mat use karo: "kar sakti hoon", "batati hoon", "bataungi".

Context:
{context}

Pichli baat:
{history}

User ka sawaal: {question}
"""

EN_REFUSAL = "I don't know that information. Please contact Rajasthali support for details."
HI_REFUSAL = "Yeh jankari mere paas nahi hai. Kripya Rajasthali support se sampark karein."

en_prompt = ChatPromptTemplate.from_template(EN_TEMPLATE)
hi_f_prompt = ChatPromptTemplate.from_template(HI_FEMALE_TEMPLATE)
hi_m_prompt = ChatPromptTemplate.from_template(HI_MALE_TEMPLATE)


def is_hindi_voice(voice: str) -> bool:
    v = (voice or "").lower()
    return bool(re.match(r"^hi[-_]", v))


def is_female_hindi_voice(voice: str) -> bool:
    # Current supported Hindi voices: Swara (female), Madhur (male)
    v = (voice or "").lower()
    return "swara" in v


def pick_prompt(voice: str) -> ChatPromptTemplate:
    if not is_hindi_voice(voice):
        return en_prompt
    return hi_f_prompt if is_female_hindi_voice(voice) else hi_m_prompt


# ---------------- GREETING ----------------
_GREETING_RE = re.compile(r"[^a-zA-Z]+")


def is_greeting_only(text: str) -> bool:
    cleaned = _GREETING_RE.sub(" ", (text or "").strip().lower())
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        return False

    greetings = {
        "hi",
        "hello",
        "hey",
        "namaste",
        "namaskar",
        "pranam",
        "hii",
        "heyy",
        "hola",
        "good morning",
        "good afternoon",
        "good evening",
        "gm",
        "ga",
        "ge",
    }
    if cleaned in greetings:
        return True

    filler_ok = {
        "hi",
        "hello",
        "hey",
        "namaste",
        "namaskar",
        "pranam",
        "ji",
        "haan",
        "han",
        "yes",
        "sir",
        "madam",
    }
    parts = cleaned.split()
    if len(parts) <= 3 and all(p in filler_ok for p in parts):
        return True
    return False


def canned_greeting(voice: str) -> str:
    if is_hindi_voice(voice):
        if is_female_hindi_voice(voice):
            return "Rajasthali mein aapka swagat hai! Main aapki kaise madad kar sakti hoon?"
        return "Rajasthali mein aapka swagat hai! Main aapki kaise madad kar sakta hoon?"
    return "Welcome to Rajasthali! How can I help you today?"


def refusal_for_voice(voice: str) -> str:
    return HI_REFUSAL if is_hindi_voice(voice) else EN_REFUSAL

