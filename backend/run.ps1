$ErrorActionPreference = "Stop"

# Configure CORS for your Next.js origins (LAN + local)
$env:CORS_ORIGINS = "http://192.168.1.4:3000,http://localhost:3000,http://127.0.0.1:3000"

# Optional: configure model choices here if you want
# $env:OLLAMA_LLM_MODEL = "llama3.1:8b-instruct-q4_K_M"
# $env:OLLAMA_EMBED_MODEL = "nomic-embed-text"

uvicorn app:app --host 0.0.0.0 --port 8000 --reload

