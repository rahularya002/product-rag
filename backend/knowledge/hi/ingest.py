from pathlib import Path
import json

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
DB_DIR = BASE_DIR / "db"

print("📂 Knowledge folder:", KNOWLEDGE_DIR)

all_docs = []

# -----------------------------
# 1️⃣ LOAD ALL .MD + .TXT RECURSIVELY
# -----------------------------
for file in KNOWLEDGE_DIR.rglob("*"):
    if file.suffix.lower() in [".md", ".txt"]:
        print("📄 Loading:", file.name)
        loader = TextLoader(str(file), encoding="utf-8")
        docs = loader.load()
        all_docs.extend(docs)

# -----------------------------
# 2️⃣ LOAD JSON BRAIN FILE
# -----------------------------
brain_file = KNOWLEDGE_DIR / "rajasthali_brain.json"

if brain_file.exists():
    print("🧠 Loading JSON brain...")
    with open(brain_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    json_text = json.dumps(data, indent=2, ensure_ascii=False)

    all_docs.append(
        Document(
            page_content=json_text,
            metadata={"source": "rajasthali_brain.json"}
        )
    )

print("📊 Total documents loaded:", len(all_docs))

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

print("✂️ Total chunks created:", len(chunks))

# -----------------------------
# 4️⃣ EMBEDDINGS MODEL (MULTILINGUAL)
# -----------------------------
print("🔎 Creating embeddings...")
embeddings = OllamaEmbeddings(model="mxbai-embed-large")

# -----------------------------
# 5️⃣ REBUILD VECTOR DB (CLEAN)
# -----------------------------
if DB_DIR.exists():
    import shutil
    shutil.rmtree(DB_DIR)
    print("🗑️ Old DB deleted")

db = Chroma.from_documents(
    chunks,
    embeddings,
    persist_directory=str(DB_DIR)
)

print("✅ Knowledge base created successfully!")