@echo off
setlocal

REM Configure CORS for your Next.js origins (LAN + local)
set CORS_ORIGINS=http://192.168.1.4:3000,http://localhost:3000,http://127.0.0.1:3000

REM Optional: configure model choices here if you want
REM set OLLAMA_LLM_MODEL=llama3.1:8b-instruct-q4_K_M
REM set OLLAMA_EMBED_MODEL=nomic-embed-text

uvicorn app:app --host 0.0.0.0 --port 8000 --reload

