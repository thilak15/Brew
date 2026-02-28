"use client";

import { useCallback, useEffect, useRef } from "react";
import type { BrewAction } from "./orderReducer";
import { interruptAudioPlayback } from "./audioPipeline";

const WS_URL =
  typeof window !== "undefined"
    ? (process.env.NEXT_PUBLIC_WS_URL ||
      `ws://${window.location.hostname}:8000`)
    : "";

export type UseBrewWebSocketOptions = {
  user_id?: string;
  session_id?: string;
  dispatch: React.Dispatch<BrewAction>;
  connect: boolean;
  onAudioChunk?: (buffer: ArrayBuffer) => void;
};

export function useBrewWebSocket({
  user_id = "user",
  session_id = "session",
  dispatch,
  connect,
  onAudioChunk,
}: UseBrewWebSocketOptions): {
  sendAudio: (chunk: ArrayBuffer) => void;
  sendText: (text: string) => void;
  disconnect: () => void;
} {
  const wsRef = useRef<WebSocket | null>(null);
  const dispatchRef = useRef(dispatch);
  const onAudioChunkRef = useRef(onAudioChunk);
  dispatchRef.current = dispatch;
  onAudioChunkRef.current = onAudioChunk;

  const disconnect = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!connect || !WS_URL) return;
    const url = `${WS_URL.replace(/\/$/, "")}/ws/${encodeURIComponent(user_id)}/${encodeURIComponent(session_id)}`;
    dispatchRef.current({ type: "CONNECTION", status: "connecting" });
    const ws = new WebSocket(url);
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;

    ws.onopen = () => {
      dispatchRef.current({ type: "CONNECTION", status: "open" });
      dispatchRef.current({ type: "MODE", mode: "listening" });
    };
    ws.onerror = () => {
      dispatchRef.current({
        type: "CONNECTION",
        status: "error",
        error: "WebSocket error",
      });
    };
    ws.onclose = () => {
      wsRef.current = null;
      dispatchRef.current({ type: "CONNECTION", status: "idle" });
      dispatchRef.current({ type: "MODE", mode: "idle" });
    };
    ws.onmessage = (event: MessageEvent) => {
      const d = dispatchRef.current;
      if (event.data instanceof ArrayBuffer) {
        onAudioChunkRef.current?.(event.data);
        return;
      }
      try {
        const msg = JSON.parse(event.data as string);
        if (msg.type === "order_state" && msg.payload) {
          d({ type: "ORDER_STATE", payload: msg.payload });
          return;
        }
        if (msg.type === "error") {
          d({ type: "ERROR", message: msg.message || msg.code || "Error" });
          return;
        }
        if (msg.interrupted) {
          interruptAudioPlayback();
        }
        if (msg.turnComplete === true) {
          d({ type: "MODE", mode: "listening" });
        }
        if (msg.inputTranscription != null) {
          const text =
            typeof msg.inputTranscription === "string"
              ? msg.inputTranscription
              : (msg.inputTranscription as { text?: string })?.text ?? String(msg.inputTranscription);
          d({ type: "TRANSCRIPT", text });
          d({ type: "MENU_CONTEXT", context: text });
        }
        if (msg.content?.parts) {
          const hasAudio = msg.content.parts.some(
            (p: { inlineData?: unknown }) => p.inlineData
          );
          if (hasAudio) d({ type: "MODE", mode: "speaking" });
        }
      } catch {
        // ignore non-JSON
      }
    };
    return () => {
      disconnect();
    };
  }, [connect, user_id, session_id, disconnect]);

  const sendAudio = useCallback((chunk: ArrayBuffer) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(chunk);
    }
  }, []);

  const sendText = useCallback((text: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "text", text }));
    }
  }, []);

  return { sendAudio, sendText, disconnect };
}
