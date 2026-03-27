from pathlib import Path
import json
import time

from langchain_community.document_loaders import TextLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_ollama import OllamaEmbeddings
from langchain_community.vectorstores import Chroma


# -----------------------------
# Paths (robust)
# -----------------------------
BASE_DIR = Path(__file__).resolve().parent
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
DB_RUNS_DIR = BASE_DIR / "db_runs"
DB_DIR = DB_RUNS_DIR / f"db_{int(time.time())}"
ACTIVE_DB_POINTER = BASE_DIR / ".chroma_dir"

print("Knowledge folder:", KNOWLEDGE_DIR)

all_docs = []

def infer_lang(p: Path) -> str:
    parts = {x.lower() for x in p.parts}
    if "hi" in parts:
        return "hi"
    if "en" in parts:
        return "en"
    return "unknown"

# -----------------------------
# 1️⃣ LOAD ALL .MD + .TXT RECURSIVELY
# -----------------------------
for file in KNOWLEDGE_DIR.rglob("*"):
    if file.suffix.lower() in [".md", ".txt"]:
        print("Loading:", file.name)
        loader = TextLoader(str(file), encoding="utf-8")
        docs = loader.load()
        rel = file.relative_to(KNOWLEDGE_DIR).as_posix()
        for d in docs:
            d.metadata = {
                **(d.metadata or {}),
                "source": rel,
                "lang": infer_lang(file),
            }
        all_docs.extend(docs)

# -----------------------------
# 2️⃣ LOAD JSON BRAIN FILE
# -----------------------------
brain_file = KNOWLEDGE_DIR / "rajasthali_brain.json"

if brain_file.exists():
    print("Loading JSON brain...")
    with open(brain_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    json_text = json.dumps(data, indent=2, ensure_ascii=False)

    all_docs.append(
        Document(
            page_content=json_text,
            metadata={"source": "rajasthali_brain.json", "lang": "neutral"}
        )
    )

print("Total documents loaded:", len(all_docs))

if len(all_docs) == 0:
    raise Exception("❌ No documents found in knowledge folder!")

# -----------------------------
# 3️⃣ SPLIT DOCUMENTS
# -----------------------------
splitter = RecursiveCharacterTextSplitter(
    chunk_size=800,
    chunk_overlap=120
)

chunks = splitter.split_documents(all_docs)

print("Total chunks created:", len(chunks))

# -----------------------------
# 4️⃣ EMBEDDINGS MODEL (MULTILINGUAL)
# -----------------------------
print("Creating embeddings...")
embeddings = OllamaEmbeddings(model="nomic-embed-text")

# -----------------------------
# 5️⃣ BUILD VECTOR DB (VERSIONED DIR)
# -----------------------------
DB_DIR.parent.mkdir(parents=True, exist_ok=True)

db = Chroma.from_documents(
    chunks,
    embeddings,
    persist_directory=str(DB_DIR)
)

ACTIVE_DB_POINTER.write_text(str(DB_DIR), encoding="utf-8")
print("Knowledge base created successfully!")
print("Active Chroma dir:", DB_DIR)