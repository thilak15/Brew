"use client";

function trimTrailingSlash(url: string): string {
  return url.replace(/\/$/, "");
}

export function getWsUrl(): string {
  if (typeof window === "undefined") return "";
  // 1) Explicit env var wins (used in Cloud Run builds)
  if (process.env.NEXT_PUBLIC_WS_URL) {
    return trimTrailingSlash(process.env.NEXT_PUBLIC_WS_URL);
  }
  // 2) Local development fallback
  if (
    window.location.hostname === "localhost" ||
    window.location.hostname === "127.0.0.1"
  ) {
    return "ws://localhost:8000";
  }
  // 3) Production fallback: same host, backend exposed on 8000
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.hostname}:8000`;
}

export function getApiBaseUrl(): string {
  if (typeof window === "undefined") return "";
  if (process.env.NEXT_PUBLIC_API_URL) {
    return trimTrailingSlash(process.env.NEXT_PUBLIC_API_URL);
  }
  const wsUrl = getWsUrl();
  if (!wsUrl) return "";
  if (wsUrl.startsWith("wss://")) {
    return wsUrl.replace(/^wss:\/\//, "https://");
  }
  if (wsUrl.startsWith("ws://")) {
    return wsUrl.replace(/^ws:\/\//, "http://");
  }
  return "";
}
