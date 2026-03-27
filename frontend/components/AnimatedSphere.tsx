"use client";

import { motion, Variants } from "framer-motion";

interface AnimatedSphereProps {
    state: "idle" | "listening" | "speaking";
}

export function AnimatedSphere({ state }: AnimatedSphereProps) {
    const sphereVariants: Variants = {
        idle: {
            scale: 1,
            opacity: 0.2, // Very subtle when idle
            transition: { duration: 1 },
        },
        listening: {
            scale: [1, 1.05, 1],
            opacity: [0.6, 1, 0.6],
            transition: { repeat: Infinity, duration: 2, ease: "easeInOut" },
        },
        speaking: {
            scale: [1, 1.25, 0.95, 1.15, 1],
            opacity: [0.8, 1, 0.7, 0.9, 0.8],
            transition: { repeat: Infinity, duration: 0.7, ease: "easeInOut" }, // Faster, dynamic pulsing
        },
    };

    return (
        <div className="relative flex h-32 w-32 items-center justify-center">
            {/* Outer Glow / Halo rings */}
            {state !== "idle" && (
                <>
                    <motion.div
                        animate={{ scale: [1, 1.6], opacity: [0.3, 0] }}
                        transition={{ repeat: Infinity, duration: 2, ease: "easeOut" }}
                        className={`absolute inset-0 m-auto h-16 w-16 rounded-full border ${state === "listening" ? "border-sky-400" : "border-pink-500"}`}
                    />
                    <motion.div
                        animate={{ scale: [1, 1.3], opacity: [0.5, 0] }}
                        transition={{ repeat: Infinity, duration: 1.5, ease: "easeOut", delay: 0.2 }}
                        className={`absolute inset-0 m-auto h-16 w-16 rounded-full border ${state === "listening" ? "border-indigo-400" : "border-purple-500"}`}
                    />
                </>
            )}

            {/* Main Sphere */}
            <motion.div
                animate={state}
                variants={sphereVariants}
                className={`h-16 w-16 rounded-full shadow-[0_0_40px_rgba(0,0,0,0.5)] bg-gradient-to-br ${state === "idle"
                    ? "from-zinc-700 to-zinc-900"
                    : state === "listening"
                        ? "from-sky-400 via-indigo-500 to-purple-600 shadow-[0_0_30px_rgba(99,102,241,0.6)]"
                        : "from-pink-500 via-purple-500 to-indigo-600 shadow-[0_0_40px_rgba(236,72,153,0.7)]"
                    }`}
            />
        </div>
    );
}
