"use client";

import type { AudioMode, ConnectionStatus } from "@/lib/orderReducer";

type AudioVisualizerProps = {
  mode: AudioMode;
  connection: ConnectionStatus;
};

export function AudioVisualizer({ mode, connection }: AudioVisualizerProps) {
  const label =
    connection === "connecting"
      ? "Connecting…"
      : connection === "error"
        ? "Error"
        : connection !== "open"
          ? "Disconnected"
          : mode === "listening"
            ? "Listening"
            : mode === "thinking"
              ? "Thinking"
              : mode === "speaking"
                ? "Speaking"
                : "Ready";

  const pulse =
    connection === "open" && (mode === "listening" || mode === "speaking");
  const scale = pulse ? "scale-110" : "scale-100";

  const orbColor =
    connection === "open"
      ? mode === "listening"
        ? "bg-green-500 shadow-green-500/50"
        : mode === "speaking"
          ? "bg-blue-500 shadow-blue-500/50"
          : mode === "thinking"
            ? "bg-amber-500 shadow-amber-500/50"
            : "bg-gray-400"
      : connection === "connecting"
        ? "bg-amber-400 shadow-amber-400/50"
        : "bg-gray-300";

  return (
    <div className="flex items-center justify-center gap-3 py-2 px-4 rounded-full bg-[#FAF4ED] border border-[#E8DCCB] shadow-inner">
      <span className={`text-xl ${pulse ? "animate-bounce" : ""}`}>
        {connection === "connecting"
          ? "⏳"
          : connection === "error"
            ? "❌"
            : connection !== "open"
              ? "☕️💤"
              : mode === "listening"
                ? "☕️✨"
                : mode === "thinking"
                  ? "🤔"
                  : mode === "speaking"
                    ? "🗣️💬"
                    : "☕️"}
      </span>
      <span className="text-sm font-bold tracking-wide text-[#8D7B68] uppercase">
        {label}
      </span>
    </div>
  );
}
