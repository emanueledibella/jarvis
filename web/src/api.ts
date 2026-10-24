export type Json = Record<string, any>;
declare global {
  interface Window {
    __JARVIS_TOKEN__?: string;
    __JARVIS_NATIVE__?: boolean;
  }
}

const fragment = new URLSearchParams(location.hash.slice(1));
const fromURL = fragment.get("token");
if (fromURL) {
  sessionStorage.setItem("jarvis-token", fromURL);
  history.replaceState(null, "", location.pathname);
}
let token =
  window.__JARVIS_TOKEN__ || sessionStorage.getItem("jarvis-token") || "";
export function setToken(value: string) {
  token = value;
  sessionStorage.setItem("jarvis-token", value);
}
export function hasToken() {
  return Boolean(token);
}

export async function api<T = any>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch("/api" + path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: "Bearer " + token,
      ...options.headers,
    },
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(
      typeof detail.detail === "string"
        ? detail.detail
        : response.status === 422
          ? "Controlla i campi: uno o più valori non sono validi."
          : `Servizio non disponibile (${response.status}).`,
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
  while (!signal.aborted) {
    try {
      const response = await fetch("/api/events?after=" + cursor, {
        headers: { Authorization: "Bearer " + token },
        signal,
      });
      if (!response.ok || !response.body)
        throw new Error("Stream non disponibile");
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
