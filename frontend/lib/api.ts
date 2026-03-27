const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/+$/, "") ??
  "http://127.0.0.1:8000";

// Allow storing short text chat history on window for backend context.
declare global {
  interface Window {
    __CHAT_HISTORY__?: string[];
  }
}

/* ---------- TYPES ---------- */
export type VoiceSettings = {
  speed: number;
  pitch: number;
  volume: number;
  voice: string;
};

/* ---------- STREAM AI TEXT ---------- */
export async function streamAI(
  question: string,
  settings: VoiceSettings,
  onChunk: (chunk: string) => void
) {
  const res = await fetch(`${API_BASE_URL}/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      voice: settings.voice,
      history: window.__CHAT_HISTORY__ ?? []
    }),
  });

  if (!res.ok) {
    throw new Error(`Request failed: ${res.status} ${res.statusText}`);
  }
  if (!res.body) {
    throw new Error("No response body (streaming not supported?)");
  }

  // Robust SSE parsing: buffer by event delimiter (\n\n) and
  // decode incrementally to avoid breaking multibyte characters.
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const flushEvent = (eventBlock: string) => {
    // Collect data lines, ignore other fields (event:, id:, retry:)
    const dataLines: string[] = [];
    for (const rawLine of eventBlock.split("\n")) {
      const line = rawLine.replace(/\r$/, "");
      if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).replace(/^\s/, "")); // keep spacing as-is
      }
    }
    if (dataLines.length === 0) return;
    const payload = dataLines.join("\n");
    if (!payload || payload === "[DONE]") return;
    onChunk(payload);
  };

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const eventBlock = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      if (eventBlock.trim().length === 0) continue;
      flushEvent(eventBlock);
    }
  }

  // flush any trailing block (if server ended without delimiter)
  if (buffer.trim().length) flushEvent(buffer);
}

/* ---------- STREAM VOICE ---------- */
export async function streamVoice(
  text: string,
  settings: VoiceSettings,
  opts?: { signal?: AbortSignal; autoplay?: boolean }
) {
  const res = await fetch(`${API_BASE_URL}/stream_tts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    signal: opts?.signal,
    body: JSON.stringify({
      question: text,
      speed: settings.speed,
      pitch: settings.pitch,
      volume: settings.volume,
      voice: settings.voice,
    }),
  });

  if (!res.ok) {
    throw new Error(`TTS failed: ${res.status} ${res.statusText}`);
  }

  const autoplay = opts?.autoplay ?? true;

  // Prefer true streaming playback for lower latency.
  // Fallback to blob playback if MediaSource isn't available/supported.
  const canStream =
    typeof window !== "undefined" &&
    "MediaSource" in window &&
    typeof MediaSource !== "undefined" &&
    typeof (MediaSource as any).isTypeSupported === "function" &&
    (MediaSource as any).isTypeSupported('audio/mpeg') &&
    !!res.body;

  if (!canStream) {
    const blob = await res.blob();
    const audioUrl = URL.createObjectURL(blob);
    const audio = new Audio(audioUrl);
    if (autoplay) await audio.play();
    return { audio, audioUrl };
  }

  const mediaSource = new MediaSource();
  const audioUrl = URL.createObjectURL(mediaSource);
  const audio = new Audio(audioUrl);

  const reader = res.body!.getReader();
  let sourceBuffer: SourceBuffer | null = null;
  let ended = false;

  const pump = async () => {
    const append = (chunk: Uint8Array) =>
      new Promise<void>((resolve, reject) => {
        if (!sourceBuffer) return reject(new Error("No SourceBuffer"));
        const onUpdateEnd = () => {
          sourceBuffer?.removeEventListener("updateend", onUpdateEnd);
          resolve();
        };
        sourceBuffer.addEventListener("updateend", onUpdateEnd);
        try {
          // Copy into a dedicated ArrayBuffer (avoid SharedArrayBuffer typing).
          const copy = new Uint8Array(chunk.byteLength);
          copy.set(chunk);
          sourceBuffer.appendBuffer(copy.buffer);
        } catch (e) {
          sourceBuffer.removeEventListener("updateend", onUpdateEnd);
          reject(e);
        }
      });

    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        if (opts?.signal?.aborted) break;
        if (value && value.byteLength) {
          // Wait if SourceBuffer is still updating.
          while (sourceBuffer?.updating) {
            await new Promise((r) => setTimeout(r, 10));
          }
          await append(value);
        }
      }
    } finally {
      ended = true;
      try {
        while (sourceBuffer?.updating) {
          await new Promise((r) => setTimeout(r, 10));
        }
        if (mediaSource.readyState === "open") mediaSource.endOfStream();
      } catch {
        // ignore end-of-stream issues
      }
    }
  };

  mediaSource.addEventListener("sourceopen", () => {
    if (sourceBuffer) return;
    try {
      sourceBuffer = mediaSource.addSourceBuffer("audio/mpeg");
      sourceBuffer.mode = "sequence";
      void pump();
    } catch {
      // If SourceBuffer creation fails, fall back to blob.
      // We can't re-run fetch here (body already in use), so just end stream.
      try {
        if (!ended && mediaSource.readyState === "open") mediaSource.endOfStream();
      } catch {}
    }
  });

  if (autoplay) await audio.play();
  return { audio, audioUrl };
}

/* ---------- SPEECH TEXT POLISH (NO RESPEAK) ---------- */
export async function polishSpeech(text: string, voice: string) {
  const res = await fetch(`${API_BASE_URL}/polish_speech`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, voice }),
  });

  if (!res.ok) {
    throw new Error(`Speech polish failed: ${res.status} ${res.statusText}`);
  }

  return (await res.json()) as { spokenText: string };
}

export async function finalizeText(text: string, voice: string) {
  const res = await fetch(`${API_BASE_URL}/finalize_text`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, voice }),
  });

  if (!res.ok) {
    throw new Error(`Finalize failed: ${res.status} ${res.statusText}`);
  }

  return (await res.json()) as { answer: string };
}