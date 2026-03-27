from __future__ import annotations

import os
import re
import asyncio
from pathlib import Path
from typing import List

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from langchain_ollama import OllamaLLM, OllamaEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.documents import Document

from rag.postprocess import post_process as rag_post_process, remove_devanagari as rag_remove_devanagari
from rag.prompts import (
    canned_greeting as rag_canned_greeting,
    is_greeting_only as rag_is_greeting_only,
    is_hindi_voice as rag_is_hindi_voice,
    pick_prompt as rag_pick_prompt,
    refusal_for_voice as rag_refusal_for_voice,
)
from rag.retrieval import build_context as rag_build_context

import edge_tts

app = FastAPI()

# ---------------- CORS ----------------
cors_origins = os.environ.get("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
allow_origins = [o.strip() for o in cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins or ["http://localhost:3000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- VECTOR DB ----------------
BASE_DIR = Path(__file__).resolve().parent
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
_env_chroma_dir = os.environ.get("CHROMA_DIR")
_pointer = BASE_DIR / ".chroma_dir"
if _env_chroma_dir:
    CHROMA_DIR = Path(_env_chroma_dir)
elif _pointer.exists():
    CHROMA_DIR = Path(_pointer.read_text(encoding="utf-8").strip())
else:
    CHROMA_DIR = BASE_DIR / "/product-rag/backend/db_runs/db_1774617048"

embeddings = OllamaEmbeddings(model=os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text"))
db = Chroma(persist_directory=str(CHROMA_DIR), embedding_function=embeddings)

# ---------------- LLMs ----------------
llm = OllamaLLM(
    model=os.environ.get("OLLAMA_LLM_MODEL", "qwen2.5:7b-instruct"),
    temperature=float(os.environ.get("OLLAMA_TEMPERATURE", "0.0")),  # Lower = less hallucination
)

speech_llm = OllamaLLM(
    model=os.environ.get("OLLAMA_SPEECH_LLM_MODEL", "qwen2.5:7b-instruct"),
    temperature=float(os.environ.get("OLLAMA_SPEECH_TEMPERATURE", "0.1")),
)

# Dedicated grammar rewrite LLM — use the stronger model if available
grammar_llm = OllamaLLM(
    model=os.environ.get("OLLAMA_GRAMMAR_LLM_MODEL", os.environ.get("OLLAMA_SPEECH_LLM_MODEL", "qwen2.5:7b-instruct")),
    temperature=0.0,  # Deterministic for grammar correction
)

# ---------------- PROMPTS ----------------
# ---- English prompt ----
EN_TEMPLATE = """
You are the official AI assistant for Rajasthali, a premium Indian handicraft brand.

STRICT RULES — follow all of them without exception:
1. Answer ONLY from the Context below. Do NOT invent, infer, or assume any detail not present.
2. If the answer is not in Context, respond EXACTLY: "I don't have that information. Please contact Rajasthali support for details."
3. Do NOT add product names, prices, policies, or features unless they appear verbatim in Context.
4. For greetings or small talk only, you may respond warmly without using Context.
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
4. Greeting ya small talk ke liye warmly respond kar sakti ho — Context ki zarurat nahi.
5. Kabhi bhi "Namaste", "Hi", "Hello" se jawab shuru mat karo.
6. Jawab concise aur factual rakho.
7. Sirf ROMAN LIPI (English letters) mein Hindi likho — Devanagari BILKUL NAHI.
8. FEMALE grammar use karo: "kar sakti hoon", "batati hoon", "bataungi", "hoon", "main".
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
4. Greeting ya small talk ke liye warmly respond kar sakta ho — Context ki zarurat nahi.
5. Kabhi bhi "Namaste", "Hi", "Hello" se jawab shuru mat karo.
6. Jawab concise aur factual rakho.
7. Sirf ROMAN LIPI (English letters) mein Hindi likho — Devanagari BILKUL NAHI.
8. MALE grammar use karo: "kar sakta hoon", "batata hoon", "bataunga", "hoon", "main".
   Female forms BILKUL mat use karo: "kar sakti hoon", "batati hoon", "bataungi".

Context:
{context}

Pichli baat:
{history}

User ka sawaal: {question}
"""

en_prompt   = ChatPromptTemplate.from_template(EN_TEMPLATE)
hi_f_prompt = ChatPromptTemplate.from_template(HI_FEMALE_TEMPLATE)
hi_m_prompt = ChatPromptTemplate.from_template(HI_MALE_TEMPLATE)


def pick_prompt(voice: str) -> ChatPromptTemplate:
    if not voice.startswith("hi-"):
        return en_prompt
    is_female = any(v in voice for v in ["Swara", "Aria"])
    return hi_f_prompt if is_female else hi_m_prompt


# ---------------- KNOWLEDGE LOADER ----------------
def load_system_behavior(lang: str) -> str:
    path = KNOWLEDGE_DIR / lang / "00_system_behavior.md"
    try:
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return ""


# ---------------- DOCS ----------------
def format_docs(docs: List[Document]) -> str:
    if not docs:
        return "No relevant context found."
    parts: List[str] = []
    for d in docs:
        src  = (d.metadata or {}).get("source", "unknown")
        lang = (d.metadata or {}).get("lang", "unknown")
        parts.append(f"[{lang}] ({src})\n{d.page_content}".strip())
    return "\n\n---\n\n".join(parts)


def get_docs(question: str, voice: str) -> List[Document]:
    lang = "hi" if voice.startswith("hi-") else "en"
    k = int(os.environ.get("RETRIEVAL_K", "6"))

    def safe_retrieve(filter_value: str | None) -> List[Document]:
        try:
            search_kwargs = {"k": k}
            if filter_value is not None:
                search_kwargs["filter"] = {"lang": filter_value}
            return db.as_retriever(search_kwargs=search_kwargs).invoke(question)
        except Exception:
            return db.as_retriever(search_kwargs={"k": k}).invoke(question)

    primary = safe_retrieve(lang)
    neutral = safe_retrieve("neutral")

    seen: set = set()
    merged: List[Document] = []
    for d in primary + neutral:
        key = ((d.metadata or {}).get("source"), d.page_content[:80])
        if key in seen:
            continue
        seen.add(key)
        merged.append(d)
    return merged


# ---------------- GREETING ----------------
_GREETING_RE   = re.compile(r"[^a-zA-Z]+")

def is_greeting_only(text: str) -> bool:
    cleaned = _GREETING_RE.sub(" ", (text or "").strip().lower())
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        return False

    greetings = {
        "hi", "hello", "hey", "namaste", "namaskar", "pranam",
        "hii", "heyy", "hola", "good morning", "good afternoon",
        "good evening", "gm", "ga", "ge",
    }
    if cleaned in greetings:
        return True

    filler_ok = {
        "hi", "hello", "hey", "namaste", "namaskar", "pranam",
        "ji", "haan", "han", "yes", "sir", "madam",
    }
    parts = cleaned.split()
    if len(parts) <= 3 and all(p in filler_ok for p in parts):
        return True
    return False


def canned_greeting(voice: str) -> str:
    is_hindi  = voice.startswith("hi-")
    is_female = any(v in voice for v in ["Swara", "Aria"])

    if is_hindi:
        if is_female:
            return "Rajasthali mein aapka swagat hai! Main aapki kaise madad kar sakti hoon?"
        return "Rajasthali mein aapka swagat hai! Main aapki kaise madad kar sakta hoon?"
    return "Welcome to Rajasthali! How can I help you today?"


# ---------------- POST-PROCESSING ----------------
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
    out  = text.strip()
    out2 = _META_TRAIL_RE.sub("", out).strip()
    return out2 or out


# ---- Gender violation detection ----
_MALE_MARKERS = [
    "kar sakta hoon", "kar sakta hun",
    "batata hoon", "batata hun",
    "bataunga", "kar sakta",
    "ban gaya hoon", "ban chuka hoon",
]
_FEMALE_MARKERS = [
    "kar sakti hoon", "kar sakti hun",
    "batati hoon", "batati hun",
    "bataungi", "kar sakti",
    "ban gayi hoon", "ban chuki hoon",
]

def _contains_any(text: str, needles: list[str]) -> bool:
    t = (text or "").lower()
    return any(n in t for n in needles)

def has_gender_violation(answer: str, voice: str) -> bool:
    if not voice.startswith("hi-"):
        return False
    is_female = any(v in voice for v in ["Swara", "Aria"])
    if is_female:
        return _contains_any(answer, _MALE_MARKERS)
    return _contains_any(answer, _FEMALE_MARKERS)


def rewrite_with_correct_gender(answer: str, voice: str) -> str:
    """
    Targeted grammar rewrite using grammar_llm (temp=0.0).
    Only fixes gender markers — preserves all factual content.
    """
    if not voice.startswith("hi-"):
        return answer

    is_female = any(v in voice for v in ["Swara", "Aria"])
    gender     = "FEMALE" if is_female else "MALE"
    must_use   = "kar sakti hoon / batati hoon / bataungi" if is_female else "kar sakta hoon / batata hoon / bataunga"
    must_avoid = "kar sakta hoon / batata hoon / bataunga" if is_female else "kar sakti hoon / batati hoon / bataungi"

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


def post_process(text: str, voice: str, is_greeting_response: bool = False) -> str:
    """
    Full post-processing pipeline:
    1. Remove stray Devanagari (Hindi voices only)
    2. Strip leading greeting (if not a greeting response)
    3. Fix gender violations
    4. Strip meta notes
    """
    out = text or ""

    if voice.startswith("hi-"):
        out = remove_devanagari(out)

    if not is_greeting_response:
        out = strip_leading_greeting(out)

    if has_gender_violation(out, voice):
        out = rewrite_with_correct_gender(out, voice)
        out = strip_leading_greeting(out)      # model may re-add greeting in rewrite

    out = strip_meta_notes(out)
    return out.strip()


# ---------------- HISTORY ----------------
def build_chat_history(history: list[str]) -> str:
    if not history:
        return "No previous conversation."
    # Last 3 turns (6 messages: user + assistant alternating)
    return "\n".join(history[-6:])


# ---------------- MODELS ----------------
class Question(BaseModel):
    question: str
    voice: str = "en-US-AriaNeural"
    history: list[str] = []


class TTSRequest(BaseModel):
    question: str
    speed: float = 1.0
    pitch: float = 1.0
    volume: float = 1.0
    voice: str = "en-US-AriaNeural"


class SpeechPolishRequest(BaseModel):
    text: str
    voice: str = "en-US-AriaNeural"


class FinalizeTextRequest(BaseModel):
    text: str
    voice: str = "en-US-AriaNeural"


# ---------------- SHARED INVOKE HELPER ----------------
def build_chain_input(q: Question) -> tuple[dict, bool]:
    context, context_empty = rag_build_context(db, q.question, q.voice)
    history = build_chat_history(q.history)
    return {"context": context, "history": history, "question": q.question}, context_empty


# ---------------- ASK (NON-STREAM) ----------------
@app.post("/ask")
def ask(q: Question):
    if rag_is_greeting_only(q.question):
        return {"answer": rag_canned_greeting(q.voice)}

    chain_input, context_empty = build_chain_input(q)
    if context_empty:
        return {"answer": rag_refusal_for_voice(q.voice)}

    result = (rag_pick_prompt(q.voice) | llm).invoke(chain_input)
    return {"answer": rag_post_process(result, q.voice, grammar_llm)}


# ---------------- STREAM TEXT ----------------
@app.post("/stream")
async def stream_answer(q: Question, request: Request):

    if rag_is_greeting_only(q.question):
        async def greet_only():
            yield f"data: {rag_canned_greeting(q.voice)}\n\n"
            yield "event: done\ndata: [DONE]\n\n"

        return StreamingResponse(
            greet_only(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection":    "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    chain_input, context_empty = build_chain_input(q)

    if context_empty:
        async def refusal_only():
            refusal = rag_refusal_for_voice(q.voice)
            processed = rag_post_process(refusal, q.voice, grammar_llm, is_greeting_response=True)
            # Keep SSE formatting consistent.
            yield f"data: {processed}\n\n"
            yield "event: done\ndata: [DONE]\n\n"

        return StreamingResponse(
            refusal_only(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    chain = rag_pick_prompt(q.voice) | llm

    # Buffer the full response so we can post-process before sending to client.
    # This prevents gender/Devanagari artifacts from leaking mid-stream.
    # For low-latency streaming (no post-process), set env RAW_STREAM=1.
    raw_stream = os.environ.get("RAW_STREAM", "0") == "1"

    if raw_stream:
        async def generate_stream_raw():
            try:
                for chunk in chain.stream(chain_input):
                    if await request.is_disconnected():
                        break
                    if chunk:
                        # Still strip Devanagari per-chunk for Hindi voices
                        safe = rag_remove_devanagari(chunk) if rag_is_hindi_voice(q.voice) else chunk
                        if safe:
                            yield f"data: {safe}\n\n"
                    await asyncio.sleep(0)
            except Exception as e:
                yield f"event: error\ndata: {str(e)}\n\n"
            finally:
                yield "event: done\ndata: [DONE]\n\n"

        return StreamingResponse(
            generate_stream_raw(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection":    "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # Default: buffer full response, post-process, then stream chunks
    async def generate_stream_buffered():
        try:
            full = ""
            for chunk in chain.stream(chain_input):
                if await request.is_disconnected():
                    return
                full += chunk or ""

            processed = rag_post_process(full, q.voice, grammar_llm)

            # Stream the processed text in smallish chunks so the UI isn't blank
            CHUNK = 80
            for i in range(0, len(processed), CHUNK):
                if await request.is_disconnected():
                    return
                yield f"data: {processed[i:i+CHUNK]}\n\n"
                await asyncio.sleep(0)

        except Exception as e:
            yield f"event: error\ndata: {str(e)}\n\n"
        finally:
            yield "event: done\ndata: [DONE]\n\n"

    return StreamingResponse(
        generate_stream_buffered(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection":    "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------- STREAM TTS ----------------
@app.post("/stream_tts")
async def stream_tts(req: TTSRequest, request: Request):

    def pct(value: float) -> str:
        v = int(value)
        return f"+{v}%" if v >= 0 else f"{v}%"

    def hz(value: float) -> str:
        v = int(value)
        return f"+{v}Hz" if v >= 0 else f"{v}Hz"

    rate_val   = (req.speed  - 1) * 100
    pitch_val  = (req.pitch  - 1) * 50
    volume_val = (req.volume - 1) * 100

    communicate = edge_tts.Communicate(
        text=req.question,
        voice=req.voice,
        rate=pct(rate_val),
        pitch=hz(pitch_val),
        volume=pct(volume_val),
    )

    async def audio_stream():
        async for chunk in communicate.stream():
            if await request.is_disconnected():
                break
            if chunk.get("type") == "audio":
                yield chunk["data"]

    return StreamingResponse(
        audio_stream(),
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-store"},
    )


# ---------------- SPEECH TEXT POLISH ----------------
@app.post("/polish_speech")
def polish_speech(req: SpeechPolishRequest):
    if not req.text:
        return {"spokenText": ""}
    polished = rag_post_process(req.text, req.voice, grammar_llm)
    return {"spokenText": polished}


# ---------------- TEXT FINALIZE ----------------
@app.post("/finalize_text")
def finalize_text(req: FinalizeTextRequest):
    if not req.text:
        return {"answer": ""}
    return {"answer": rag_post_process(req.text, req.voice, grammar_llm)}