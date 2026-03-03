"use client";

import { useReducer, useState, useCallback, useRef, useEffect } from "react";
import {
  brewReducer,
  getInitialState,
} from "@/lib/orderReducer";
import { useBrewWebSocket } from "@/lib/useBrewWebSocket";
import { startMicCapture, playAudioChunk, prepareAudioPlayback } from "@/lib/audioPipeline";
import { SmartMenu } from "@/components/SmartMenu";
import { LiveReceipt } from "@/components/LiveReceipt";
import { AudioVisualizer } from "@/components/AudioVisualizer";

/** One tap = "I'm here" at the drive-thru: start mic and tell the agent so it greets. */
const WELCOME_TRIGGER = "System: A car has just pulled up to the drive-thru speaker. Please greet the customer immediately out loud and ask for their order.";

export default function Home() {
  const [state, dispatch] = useReducer(brewReducer, getInitialState());
  const [connect, setConnect] = useState(false);
  const [sessionId, setSessionId] = useState(() => {
    if (typeof window !== 'undefined') {
      const stored = localStorage.getItem('brew_session_id');
      if (stored) return stored;
      const newId = `session_${Math.random().toString(36).substring(2, 9)}`;
      localStorage.setItem('brew_session_id', newId);
      return newId;
    }
    return `session_new`;
  });
  const [micActive, setMicActive] = useState(false);
  const [autoStarted, setAutoStarted] = useState(false);
  const stopMicRef = useRef<(() => void) | null>(null);

  const { sendAudio, sendText } = useBrewWebSocket({
    session_id: sessionId,
    dispatch,
    connect,
    onAudioChunk: playAudioChunk,
  });

  useEffect(() => {
    if (state.connection === "idle") {
      stopMicRef.current?.();
      stopMicRef.current = null;
      setMicActive(false);
    }
  }, [state.connection]);

  const startOrder = useCallback(() => {
    prepareAudioPlayback();
    // Small delay to ensure the backend's Gemini live session is ready
    setTimeout(() => sendText(WELCOME_TRIGGER), 500);
    startMicCapture((chunk) => sendAudio(chunk)).then((stop) => {
      stopMicRef.current = stop;
      setMicActive(true);
    });
  }, [sendAudio, sendText]);

  useEffect(() => {
    if (state.connection === "open" && !micActive && !autoStarted) {
      setAutoStarted(true);
      startOrder();
    }
  }, [state.connection, micActive, autoStarted, startOrder]);

  const endOrder = useCallback(() => {
    stopMicRef.current?.();
    stopMicRef.current = null;
    setMicActive(false);
    setConnect(false);
  }, []);

  return (
    <div className="flex flex-col min-h-screen bg-[#FAF4ED] text-[#4A3219] font-sans selection:bg-[#D4A373] selection:text-white">
      <header className="px-6 py-4 flex flex-col md:flex-row items-center justify-between gap-4 sticky top-0 bg-[#FAF4ED]/80 backdrop-blur-md z-10">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-[#A3B899] rounded-2xl flex items-center justify-center shadow-sm transform -rotate-6">
            <span className="text-xl">🍵</span>
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-[#4A3219]">brew<span className="text-[#D4A373]">.</span></h1>
        </div>

        <div className="flex gap-3 mt-2 flex-wrap items-center bg-white px-5 py-2.5 rounded-full shadow-sm border border-[#E8DCCB]">
          {state.connection === "idle" ? (
            <button
              type="button"
              onClick={() => {
                const newId = `session_${Math.random().toString(36).substring(2, 9)}`;
                localStorage.setItem('brew_session_id', newId);
                setSessionId(newId);
                dispatch({ type: "ORDER_STATE", payload: [] });
                setConnect(true);
                setAutoStarted(false);
              }}
              className="px-6 py-2.5 text-sm rounded-full bg-[#D4A373] text-white hover:bg-[#C28E5C] font-semibold tracking-wide transition-all hover:shadow-md hover:-translate-y-0.5"
            >
              Drive Up 🚙
            </button>
          ) : state.connection === "open" ? (
            !micActive ? (
              <button
                type="button"
                onClick={startOrder}
                className="px-6 py-2.5 text-sm rounded-full bg-[#A3B899] text-white hover:bg-[#8CA381] font-semibold tracking-wide transition-all hover:shadow-md hover:-translate-y-0.5"
              >
                Tap to Order 🗣️
              </button>
            ) : (
              <div className="flex items-center gap-4">
                <AudioVisualizer mode={state.mode} connection={state.connection} />
                <button
                  type="button"
                  onClick={endOrder}
                  className="px-5 py-2 text-sm rounded-full bg-red-100 text-red-600 hover:bg-red-200 font-semibold transition-colors"
                >
                  Pull Forward ➡️
                </button>
              </div>
            )
          ) : state.connection === "connecting" ? (
            <span className="text-sm font-medium text-[#8D7B68] flex items-center gap-2">
              <span className="animate-pulse">☕️</span> Warming up...
            </span>
          ) : null}
          {state.error && (
            <span className="text-sm font-semibold text-red-500 bg-red-50 px-3 py-1 rounded-full">
              ⚠️ {state.error}
            </span>
          )}
        </div>
      </header>

      <main className="flex-1 grid grid-cols-1 md:grid-cols-2 gap-6 p-6 max-w-6xl mx-auto w-full">
        <section className="bg-white rounded-3xl shadow-sm border border-[#E8DCCB] overflow-hidden min-h-[400px] flex flex-col">
          <SmartMenu menuContext={state.menuContext} />
        </section>
        <section className="bg-white rounded-3xl shadow-sm border border-[#E8DCCB] overflow-hidden min-h-[400px] flex flex-col relative">
          <div className="absolute top-0 left-0 w-full h-2 bg-[#D4A373] opacity-20"></div>
          <LiveReceipt items={state.order} />
        </section>
      </main>

      {state.transcript && (
        <footer className="fixed bottom-6 left-1/2 -translate-x-1/2 bg-white/90 backdrop-blur-sm shadow-lg border border-[#E8DCCB] px-6 py-3 rounded-full text-sm font-medium text-[#8D7B68] max-w-xl truncate pointer-events-none transition-all">
          "{state.transcript}"
        </footer>
      )}
    </div>
  );
}
