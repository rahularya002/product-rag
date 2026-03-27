"use client";

import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { streamAI, streamVoice, type VoiceSettings } from "@/lib/api";
import { finalizeText, polishSpeech } from "@/lib/api";
import { AnimatedSphere } from "./AnimatedSphere";
import { ChatMessage } from "./ChatMessage";
import { motion, AnimatePresence } from "framer-motion";
import { Send, Mic, Square, Trash2, Settings2, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: number;
  kind?: "normal" | "error";
  spokenContent?: string;
};

type SpeechRecognitionEventLike = {
  results: ArrayLike<ArrayLike<{ transcript: string }>>;
};

type SpeechRecognitionLike = {
  lang: string;
  interimResults: boolean;
  maxAlternatives: number;
  onresult: ((e: SpeechRecognitionEventLike) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};

const VOICES = [
  { label: "English Female (Aria)", value: "en-US-AriaNeural" },
  { label: "English Male (Guy)", value: "en-US-GuyNeural" },
  { label: "Hindi Female (Swara)", value: "hi-IN-SwaraNeural" },
  { label: "Hindi Male (Madhur)", value: "hi-IN-MadhurNeural" },
];

export default function Chat() {
  const storageKey = "product-ai-chat:v2";
  const instanceId = useId();

  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [listening, setListening] = useState(false);
  const [autoSpeak, setAutoSpeak] = useState(true);
  const [speaking, setSpeaking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [voiceSettings, setVoiceSettings] = useState<VoiceSettings>(() => ({
    speed: 1,
    pitch: 1,
    volume: 1,
    voice: VOICES[0]?.value ?? "en-US-AriaNeural",
  }));

  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const autoSpeakRef = useRef(autoSpeak);
  const voiceSettingsRef = useRef(voiceSettings);
  const ttsAbortRef = useRef<AbortController | null>(null);
  const ttsAudioRef = useRef<HTMLAudioElement | null>(null);
  const ttsAudioUrlRef = useRef<string | null>(null);
  const ttsQueueRef = useRef<string[]>([]);
  const ttsRunningRef = useRef(false);
  const ttsTextBufferRef = useRef<string>("");
  const ttsPrefetchRef = useRef<{
    audio: HTMLAudioElement;
    audioUrl: string;
    text: string;
  } | null>(null);
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);

  const canSend = useMemo(
    () => input.trim().length > 0 && !loading,
    [input, loading]
  );

  const controlsDisabled = useMemo(() => loading, [loading]);

  const sphereState = useMemo(() => {
    if (listening) return "listening";
    if (speaking) return "speaking";
    return "idle";
  }, [listening, speaking]);

  useEffect(() => {
    autoSpeakRef.current = autoSpeak;
  }, [autoSpeak]);

  useEffect(() => {
    voiceSettingsRef.current = voiceSettings;
  }, [voiceSettings]);

  const stopSpeaking = useCallback(() => {
    ttsAbortRef.current?.abort();
    ttsAbortRef.current = null;
    ttsQueueRef.current = [];
    ttsRunningRef.current = false;
    ttsTextBufferRef.current = "";
    if (ttsPrefetchRef.current?.audioUrl) {
      try {
        URL.revokeObjectURL(ttsPrefetchRef.current.audioUrl);
      } catch {}
    }
    ttsPrefetchRef.current = null;

    const audio = ttsAudioRef.current;
    if (audio) {
      try {
        audio.pause();
        audio.currentTime = 0;
      } catch { }
    }
    ttsAudioRef.current = null;

    const url = ttsAudioUrlRef.current;
    if (url) {
      try {
        URL.revokeObjectURL(url);
      } catch { }
    }
    ttsAudioUrlRef.current = null;
    setSpeaking(false);
  }, []);

  useEffect(() => stopSpeaking, [stopSpeaking]);

  useEffect(() => {
    const raw = localStorage.getItem(storageKey);
    if (raw) {
      try {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) setMessages(parsed);
      } catch { }
    } else {
      setMessages([
        {
          id: `${instanceId}-welcome`,
          role: "assistant",
          content:
            "Hi, I'm your AI product assistant. How can I help you today? You can type a message or use your voice.",
          createdAt: Date.now(),
        },
      ]);
    }
  }, [instanceId]);

  useEffect(() => {
    localStorage.setItem(storageKey, JSON.stringify(messages.slice(-200)));
  }, [messages]);

  useEffect(() => {
    if (scrollContainerRef.current) {
      scrollContainerRef.current.scrollTop = scrollContainerRef.current.scrollHeight;
    }
  }, [messages, loading]);

  const newMsgId = () =>
    `${instanceId}-${Date.now()}-${Math.random().toString(16).slice(2)}`;

  const sendMessageText = useCallback(
    async (raw: string, currentVoice: VoiceSettings) => {
      const message = raw.trim();
      if (!message) return;

      setError(null);
      stopSpeaking();
      const userId = `${newMsgId()}-u`;

      setMessages((m) => [
        ...m,
        {
          id: userId,
          role: "user",
          content: message,
          createdAt: Date.now(),
        },
      ]);

      setLoading(true);

      const assistantId = `${newMsgId()}-a`;
      let aiText = "";

      setMessages((m) => [
        ...m,
        {
          id: assistantId,
          role: "assistant",
          content: "",
          createdAt: Date.now(),
        },
      ]);
      (window as any).__CHAT_HISTORY__ = messages
        .slice(-6)
        .map((m) => `${m.role.toUpperCase()}: ${m.content}`);

      try {
        // Sentence-level TTS queueing while text streams in.
        const enqueueTTS = (text: string) => {
          const s = text.trim();
          if (!s) return;
          ttsQueueRef.current.push(s);
          if (!ttsRunningRef.current) {
            void runTTSQueue();
          }
        };

        const prepareVoice = async (text: string) => {
          const abort = new AbortController();
          // If user hits stop, stopSpeaking() will abort the *current* request via ttsAbortRef.
          // For prefetch, we keep it separate and just let it finish; it won't play until used.
          const { audio, audioUrl } = await streamVoice(text, currentVoice, {
            signal: abort.signal,
            autoplay: false,
          });
          return { audio, audioUrl };
        };

        const runTTSQueue = async () => {
          if (ttsRunningRef.current) return;
          if (!autoSpeakRef.current) return;
          ttsRunningRef.current = true;
          setSpeaking(true);

          while (ttsQueueRef.current.length > 0) {
            if (!autoSpeakRef.current) break;
            try {
              let nextText = "";
              let usePrefetch = false;
              const prefetched = ttsPrefetchRef.current;
              if (prefetched) {
                nextText = prefetched.text;
                usePrefetch = true;
              } else {
                nextText = ttsQueueRef.current.shift() ?? "";
              }
              if (!nextText) continue;

              // If we’re consuming a prefetched chunk, also remove it from the queue head
              // (we only ever prefetch the current head).
              if (usePrefetch && ttsQueueRef.current[0] === nextText) {
                ttsQueueRef.current.shift();
              }

              const abort = new AbortController();
              ttsAbortRef.current = abort;

              let audio: HTMLAudioElement;
              let audioUrl: string;
              if (usePrefetch && ttsPrefetchRef.current) {
                ({ audio, audioUrl } = ttsPrefetchRef.current);
                ttsPrefetchRef.current = null;
              } else {
                ({ audio, audioUrl } = await streamVoice(nextText, currentVoice, {
                  signal: abort.signal,
                  autoplay: false,
                }));
              }

              ttsAudioRef.current = audio;
              ttsAudioUrlRef.current = audioUrl;

              // Start playback now.
              await audio.play();

              // Prefetch the next chunk while current audio plays (1-ahead).
              if (!ttsPrefetchRef.current && ttsQueueRef.current.length > 0) {
                const peek = ttsQueueRef.current[0];
                if (peek) {
                  void prepareVoice(peek)
                    .then(({ audio: a, audioUrl: u }) => {
                      // Only keep if we're still speaking and queue head matches.
                      if (
                        autoSpeakRef.current &&
                        ttsQueueRef.current[0] === peek
                      ) {
                        // Clear previous prefetch if any.
                        if (ttsPrefetchRef.current?.audioUrl) {
                          try {
                            URL.revokeObjectURL(ttsPrefetchRef.current.audioUrl);
                          } catch {}
                        }
                        ttsPrefetchRef.current = { audio: a, audioUrl: u, text: peek };
                        // Encourage early fetch.
                        a.preload = "auto";
                      } else {
                        try {
                          URL.revokeObjectURL(u);
                        } catch {}
                      }
                    })
                    .catch(() => {});
                }
              }

              await new Promise<void>((resolve) => {
                audio.onended = () => resolve();
                audio.onerror = () => resolve();
              });

              if (ttsAudioUrlRef.current) URL.revokeObjectURL(ttsAudioUrlRef.current);
              ttsAudioUrlRef.current = null;
              ttsAudioRef.current = null;
              ttsAbortRef.current = null;
            } catch (e) {
              if (
                e instanceof DOMException &&
                (e.name === "AbortError" || e.message.includes("aborted"))
              ) {
                break;
              }
              // skip failed chunk and continue
            }
          }

          // cleanup any prefetched audio URL
          if (ttsPrefetchRef.current?.audioUrl) {
            try {
              URL.revokeObjectURL(ttsPrefetchRef.current.audioUrl);
            } catch {}
          }
          ttsPrefetchRef.current = null;
          ttsRunningRef.current = false;
          ttsAbortRef.current = null;
          setSpeaking(false);
        };

        const flushSentencesFromBuffer = () => {
          // Emit completed sentences (or short paragraphs) from buffer.
          // Keep punctuation with the sentence for natural prosody.
          const buf = ttsTextBufferRef.current;
          if (!buf) return;

          // Split on sentence end or newline boundaries.
          const re = /(.+?[.!?]+)(\s+|$)|(.+?\n)(\s*|$)/g;
          let match: RegExpExecArray | null;
          let lastConsumed = 0;
          const sentences: string[] = [];
          while ((match = re.exec(buf)) !== null) {
            const sentence = (match[1] ?? match[3] ?? "").trim();
            if (sentence) sentences.push(sentence);
            lastConsumed = re.lastIndex;
          }
          if (lastConsumed > 0) {
            ttsTextBufferRef.current = buf.slice(lastConsumed);

            // Merge short sentences to reduce awkward pauses (fewer TTS calls).
            const MIN_CHARS = 160;
            const MAX_CHARS = 360;
            let cur = "";
            const pushCur = () => {
              const out = cur.trim();
              if (out) enqueueTTS(out);
              cur = "";
            };

            for (const s of sentences) {
              if (!cur) {
                cur = s;
                continue;
              }
              if ((cur + " " + s).length <= MAX_CHARS) {
                cur = `${cur} ${s}`;
              } else {
                pushCur();
                cur = s;
              }

              if (cur.length >= MIN_CHARS) pushCur();
            }
            pushCur();
          }
        };

        await streamAI(message, currentVoice, (chunk) => {
          aiText += chunk;
          aiText = aiText
            .replace(/([.!?])([A-Za-z])/g, "$1 $2")
            .replace(/\s{2,}/g, " ");

          setMessages((msgs) =>
            msgs.map((msg) =>
              msg.id === assistantId ? { ...msg, content: aiText } : msg
            )
          );

          if (autoSpeakRef.current) {
            ttsTextBufferRef.current += chunk;
            flushSentencesFromBuffer();
          }
        });

        // Finalize UI text correctness after streaming ends.
        // This does not re-speak; audio continues from already-queued chunks.
        void finalizeText(aiText, currentVoice.voice)
          .then(({ answer }) => {
            setMessages((msgs) =>
              msgs.map((msg) =>
                msg.id === assistantId ? { ...msg, content: answer } : msg
              )
            );
          })
          .catch(() => {});

        // Post-process spoken text only (no re-speak; current audio continues).
        void polishSpeech(aiText, currentVoice.voice)
          .then(({ spokenText }) => {
            setMessages((msgs) =>
              msgs.map((msg) =>
                msg.id === assistantId ? { ...msg, spokenContent: spokenText } : msg
              )
            );
          })
          .catch(() => {});

        // Flush any trailing text that didn't end with punctuation.
        if (autoSpeakRef.current) {
          const tail = ttsTextBufferRef.current.trim();
          ttsTextBufferRef.current = "";
          if (tail) enqueueTTS(tail);
        }
      } catch (e) {
        const msg =
          e instanceof Error
            ? e.message
            : "Request failed. Is backend running?";
        setError(msg);
      } finally {
        setLoading(false);
        textareaRef.current?.focus();
      }
    },
    [stopSpeaking, messages] // messages in dependency array was missing but safe for slice
  );

  const sendCurrentInput = async () => {
    const msg = input.trim();
    if (!msg || loading) return;
    setInput("");
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'; // Reset height
    }
    await sendMessageText(msg, voiceSettings);
  };

  useEffect(() => {
    const SpeechRecognition =
      (window as any).SpeechRecognition ||
      (window as any).webkitSpeechRecognition;

    if (!SpeechRecognition) return;

    const recognition = new SpeechRecognition();
    recognition.lang = "en-US";
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    recognition.onresult = async (e: SpeechRecognitionEventLike) => {
      const text = e.results[0][0].transcript;
      setListening(false);
      await sendMessageText(text, voiceSettingsRef.current);
    };

    recognition.onend = () => setListening(false);
    recognition.onerror = () => setListening(false);

    recognitionRef.current = recognition;
  }, [sendMessageText]);

  const startListening = () => {
    if (controlsDisabled) return;
    const recognition = recognitionRef.current;
    if (!recognition) {
      setError("Speech recognition is not supported in this browser. Try Chrome or Edge.");
      return;
    }

    if (listening) {
      recognition.stop();
      setListening(false);
      return;
    }

    setListening(true);
    recognition.start();
  };

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    e.target.style.height = 'auto';
    e.target.style.height = `${Math.min(e.target.scrollHeight, 200)}px`;
  }

  return (
    <main className="relative flex h-dvh flex-col bg-zinc-950 font-sans text-zinc-100 selection:bg-indigo-500/30">
      {/* Background gradients */}
      <div className="absolute inset-0 pointer-events-none overflow-hidden">
        <div className="absolute top-[-10%] left-[-10%] h-[40%] w-[40%] rounded-[100%] bg-indigo-900/10 mix-blend-screen blur-[100px]" />
        <div className="absolute bottom-[-10%] right-[-10%] h-[40%] w-[40%] rounded-[100%] bg-purple-900/10 mix-blend-screen blur-[100px]" />
      </div>

      <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col px-4 z-10 sm:px-6 relative h-full">
        <header className="flex items-center justify-between py-6 shrink-0 border-b border-zinc-500/10">
          <div className="flex items-center gap-3">
            <div className="flex -space-x-1">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 shadow-lg shadow-indigo-500/20">
                <Sparkles className="h-5 w-5 text-white" />
              </div>
            </div>
            <div>
              <h1 className="text-xl font-bold tracking-tight text-white drop-shadow-sm">
                Nexus AI
              </h1>
              <p className="text-xs font-medium text-zinc-400">
                Your intelligent copilot
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowSettings(!showSettings)}
              className={cn(
                "p-2.5 rounded-full transition-all duration-300",
                showSettings
                  ? "bg-zinc-800 text-white"
                  : "bg-transparent text-zinc-400 hover:bg-zinc-800/50 hover:text-zinc-200"
              )}
            >
              <Settings2 className="w-5 h-5" />
            </button>
            <button
              type="button"
              onClick={() => {
                if (!window.confirm("Clear all chats?")) return;
                stopSpeaking();
                localStorage.removeItem(storageKey);
                setMessages([
                  {
                    id: `${instanceId}-welcome`,
                    role: "assistant",
                    content: "Hi. Ready to assist.",
                    createdAt: Date.now(),
                  },
                ]);
              }}
              className="p-2.5 rounded-full text-zinc-400 hover:text-red-400 hover:bg-red-400/10 transition-colors"
              title="Clear Chat"
            >
              <Trash2 className="w-5 h-5" />
            </button>
          </div>
        </header>

        <AnimatePresence>
          {showSettings && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="overflow-hidden bg-zinc-900/50 rounded-b-2xl border-x border-b border-zinc-800/50 shrink-0 mb-4"
            >
              <div className="p-4 flex flex-wrap items-center gap-4 text-sm text-zinc-300">
                <label className="flex items-center gap-2">
                  <span className="font-medium">Voice</span>
                  <select
                    className="h-9 rounded-lg border border-zinc-700 bg-zinc-900 px-3 text-sm text-zinc-100 outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-shadow"
                    value={voiceSettings.voice}
                    onChange={(e) =>
                      setVoiceSettings((v) => ({ ...v, voice: e.target.value }))
                    }
                  >
                    {VOICES.map((v) => (
                      <option key={v.value} value={v.value}>
                        {v.label}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="flex items-center gap-2 rounded-lg border border-zinc-700 bg-zinc-900/50 px-3 py-1.5 cursor-pointer hover:bg-zinc-800 transition-colors">
                  <input
                    type="checkbox"
                    checked={autoSpeak}
                    onChange={() => setAutoSpeak((v) => !v)}
                    className="h-4 w-4 rounded border-zinc-600 bg-zinc-800 text-indigo-500 focus:ring-indigo-500/50 focus:ring-offset-zinc-900"
                  />
                  <span className="font-medium select-none">Auto speak</span>
                </label>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Central Animated Sphere for Voice/Speaking feedback */}
        <AnimatePresence>
          {(speaking || listening) && (
            <motion.div
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.8 }}
              className="flex justify-center py-6 shrink-0"
            >
              <AnimatedSphere state={sphereState} />
            </motion.div>
          )}
        </AnimatePresence>

        <section
          ref={scrollContainerRef}
          className="flex-1 overflow-y-auto scroll-smooth py-6 [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-zinc-800 hover:[&::-webkit-scrollbar-thumb]:bg-zinc-700 [&::-webkit-scrollbar-track]:bg-transparent"
        >
          <div className="space-y-6 flex flex-col padding-bottom-32">
            {messages.map((m) => (
              <ChatMessage
                key={m.id}
                id={m.id}
                role={m.role}
                content={m.content}
                createdAt={m.createdAt}
                loading={loading && m.content === ""}
                onDelete={() => setMessages((msgs) => msgs.filter((msg) => msg.id !== m.id))}
              />
            ))}
            <div ref={bottomRef} className="h-2" />
          </div>
        </section>

        <footer className="shrink-0 bg-transparent pb-6 pt-2">
          {error && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="mb-4 rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-200 flex items-center gap-2"
            >
              <div className="w-1.5 h-1.5 rounded-full bg-red-400 flex-shrink-0" />
              {error}
            </motion.div>
          )}

          <div className="relative flex items-end gap-2 max-w-4xl mx-auto backdrop-blur-xl bg-zinc-900/60 p-2 rounded-3xl border border-white/10 shadow-2xl shadow-black/50">
            <button
              type="button"
              onClick={startListening}
              disabled={controlsDisabled}
              className={cn(
                "group flex h-12 w-12 shrink-0 flex-col items-center justify-center rounded-2xl transition-all duration-300",
                controlsDisabled
                  ? "bg-zinc-800/40 text-zinc-600 cursor-not-allowed"
                  : listening
                  ? "bg-red-500 text-white shadow-lg shadow-red-500/25"
                  : "bg-zinc-800/80 text-zinc-400 hover:bg-zinc-700 hover:text-white"
              )}
              title={listening ? "Stop listening" : "Start voice input"}
            >
              {listening ? (
                <motion.div
                  animate={{ scale: [1, 1.2, 1] }}
                  transition={{ repeat: Infinity, duration: 1.5 }}
                >
                  <Square className="w-5 h-5 fill-current rounded-sm" />
                </motion.div>
              ) : (
                <Mic className="w-5 h-5 group-hover:scale-110 transition-transform" />
              )}
            </button>

            <div className="flex-1 relative group">
              <textarea
                ref={textareaRef}
                rows={1}
                value={input}
                onChange={handleInput}
                disabled={controlsDisabled}
                maxLength={2000}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    sendCurrentInput();
                  }
                }}
                className="w-full resize-none bg-transparent px-4 py-3.5 text-[15px] text-zinc-100 placeholder:text-zinc-500 outline-none min-h-[50px] max-h-[200px]"
                placeholder="Ask Nexus AI anything..."
              />
            </div>

            <div className="flex flex-col gap-2 shrink-0 self-end">
              {speaking && (
                <button
                  type="button"
                  onClick={stopSpeaking}
                  className="h-10 w-10 flex items-center justify-center rounded-xl bg-zinc-800/80 text-zinc-400 hover:bg-zinc-700 hover:text-white transition-all shadow-md group border border-white/5"
                  title="Stop AI audio"
                >
                  <Square className="w-4 h-4 fill-current group-hover:scale-110 transition-transform" />
                </button>
              )}
              <button
                type="button"
                onClick={sendCurrentInput}
                disabled={!canSend || controlsDisabled}
                className={cn(
                  "flex h-12 items-center justify-center rounded-2xl px-5 font-semibold text-sm transition-all shadow-xl group",
                  canSend && !controlsDisabled
                    ? "bg-white text-black hover:bg-zinc-200 hover:scale-[1.02]"
                    : "bg-zinc-800/50 text-zinc-500 cursor-not-allowed"
                )}
              >
                <span className="hidden sm:inline mr-2">Send</span>
                <Send className={cn("w-4 h-4", canSend && "group-hover:translate-x-1 group-hover:-translate-y-1 transition-transform duration-300")} />
              </button>
            </div>
          </div>
        </footer>
      </div>
    </main>
  );
}