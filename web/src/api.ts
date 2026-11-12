export type Json = Record<string, any>;
import { authenticatedFetch } from "./serviceTrust";
import { remoteClient } from "./remoteClient";
declare global {
  interface Window {
    __JARVIS_TOKEN__?: string;
    __JARVIS_NATIVE__?: boolean;
  }
}

const fragment = new URLSearchParams(location.hash.slice(1));
const fromURL = fragment.get("token");
if (fromURL) {
  history.replaceState(null, "", location.pathname);
}
sessionStorage.removeItem("jarvis-token");
let token = window.__JARVIS_TOKEN__ || fromURL || "";
export function setToken(value: string) {
  token = value;
}
const port = import.meta.env.DEV ? 8765 : Number(location.port || 80);
export function hasToken() {
  if (remoteClient.enabled) return remoteClient.authenticated;
  return Boolean(token);
}

export async function api<T = any>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const request = {
    ...options,
    headers: {
      ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...options.headers,
    },
  };
  const response = remoteClient.enabled
    ? await remoteClient.request("/api" + path, request)
    : await authenticatedFetch(token, port, "/api" + path, request);
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(
      typeof detail.detail === "string"
        ? detail.detail
        : response.status === 422
          ? "Check the fields: one or more values are invalid."
          : `Service unavailable (${response.status}).`,
    );
  }
  return response.json();
}
export const post = (path: string, body: Json = {}) =>
  api(path, { method: "POST", body: JSON.stringify(body) });
export const patch = (path: string, body: Json) =>
  api(path, { method: "PATCH", body: JSON.stringify(body) });

export async function eventStream(
  onEvent: (event: Json) => void,
  signal: AbortSignal,
  after = 0,
) {
  let cursor = after;
  if (remoteClient.enabled) {
    while (!signal.aborted) {
      try {
        const response = await remoteClient.request("/remote/v1/events?after=" + cursor, { signal });
        if (!response.ok) throw new Error("Event connection unavailable.");
        const batch = await response.json();
        cursor = batch.cursor;
        onEvent({ type: "connection", data: { state: "connected" } });
        for (const event of batch.events) {
          if (event.type === "notification.created" && window.jarvisCompanion?.notify)
            void window.jarvisCompanion.notify({ sequence: event.sequence, created_at: event.created_at }).catch(() => {});
          onEvent(event);
        }
      } catch {
        if (signal.aborted) return;
        onEvent({ type: "connection", data: { state: "reconnecting" } });
        await new Promise((resolve) => setTimeout(resolve, 1500));
      }
    }
    return;
  }
  while (!signal.aborted) {
    try {
      const response = await authenticatedFetch(
        token,
        port,
        "/api/events?after=" + cursor,
        {
          signal,
        },
      );
      if (!response.ok || !response.body) throw new Error("Stream unavailable");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      onEvent({ type: "connection", data: { state: "connected" } });
      while (!signal.aborted) {
        const chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true });
        const blocks = buffer.split("\n\n");
        buffer = blocks.pop() || "";
        for (const block of blocks) {
          const line = block.split("\n").find((x) => x.startsWith("data: "));
          if (!line) continue;
          const event = JSON.parse(line.slice(6));
          if (event.sequence) cursor = event.sequence;
          onEvent(event);
        }
      }
    } catch (error) {
      if (signal.aborted) return;
      onEvent({ type: "connection", data: { state: "reconnecting" } });
    }
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
}
