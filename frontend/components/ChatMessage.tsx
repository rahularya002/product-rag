import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

interface ChatMessageProps {
    id: string;
    role: "user" | "assistant";
    content: string;
    createdAt: number;
    loading?: boolean;
    onDelete?: () => void;
}

function formatTime(ts: number) {
    return new Date(ts).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
    });
}

export function ChatMessage({
    role,
    content,
    createdAt,
    loading,
    onDelete,
}: ChatMessageProps) {
    const isUser = role === "user";

    return (
        <motion.div
            initial={{ opacity: 0, y: 10, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            transition={{ duration: 0.3, ease: "easeOut" }}
            className={cn(
                "group flex w-full",
                isUser ? "justify-end" : "justify-start"
            )}
        >
            <div
                className={cn(
                    "max-w-[85%] sm:max-w-[78%] flex flex-col gap-1",
                    isUser ? "items-end" : "items-start"
                )}
            >
                <div
                    className={cn(
                        "relative whitespace-pre-wrap px-5 py-3.5 text-[15px] leading-relaxed shadow-sm",
                        isUser
                            ? "rounded-2xl rounded-tr-sm bg-indigo-600 text-white shadow-indigo-900/20"
                            : "rounded-2xl rounded-tl-sm bg-zinc-900/80 backdrop-blur-md text-zinc-100 ring-1 ring-white/5 shadow-black/50"
                    )}
                >
                    {content || (role === "assistant" && loading ? (
                        <div className="flex items-center gap-1.5 h-6">
                            <span className="w-1.5 h-1.5 rounded-full bg-zinc-400 animate-bounce" style={{ animationDelay: '0ms' }} />
                            <span className="w-1.5 h-1.5 rounded-full bg-zinc-400 animate-bounce" style={{ animationDelay: '150ms' }} />
                            <span className="w-1.5 h-1.5 rounded-full bg-zinc-400 animate-bounce" style={{ animationDelay: '300ms' }} />
                        </div>
                    ) : "")}
                </div>

                <div
                    className={cn(
                        "flex items-center gap-2 px-1 text-[11px] font-medium text-zinc-500",
                        isUser ? "flex-row-reverse" : "flex-row"
                    )}
                >
                    <span>{formatTime(createdAt)}</span>
                    {onDelete && (
                        <button
                            type="button"
                            onClick={onDelete}
                            className="hidden cursor-pointer hover:text-red-400 group-hover:inline transition-colors"
                        >
                            Delete
                        </button>
                    )}
                </div>
            </div>
        </motion.div>
    );
}
