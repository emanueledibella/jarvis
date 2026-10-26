/** Verify the local listener without disclosing the bearer token. */
export async function authenticatedFetch(
  token: string,
  port: number,
  path: string,
  options: RequestInit = {},
  fetcher: typeof fetch = fetch,
): Promise<Response> {
  if (!token || !path.startsWith("/api/"))
    throw new Error("Open Jarvis to authenticate.");
  const nonce = Array.from(crypto.getRandomValues(new Uint8Array(24)), (x) =>
    x.toString(16).padStart(2, "0"),
  ).join("");
  const controller = new AbortController();
  const abort = () => controller.abort();
  options.signal?.addEventListener("abort", abort, { once: true });
  if (options.signal?.aborted) controller.abort();
  const timer = setTimeout(abort, 6000);
  try {
    const probe = await fetcher("/health?challenge=" + nonce, {
      signal: controller.signal,
      redirect: "error",
      cache: "no-store",
    });
    if (!probe.ok || !probe.body)
      throw new Error("Local service verification failed.");
    const reader = probe.body.getReader();
    const chunks: Uint8Array[] = [];
    let length = 0;
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      length += value.length;
      if (length > 4096) {
        await reader.cancel();
        throw new Error("Local service verification failed.");
      }
      chunks.push(value);
    }
    const content = new Uint8Array(length);
    let offset = 0;
    for (const chunk of chunks) {
      content.set(chunk, offset);
      offset += chunk.length;
    }
    const proof = JSON.parse(new TextDecoder().decode(content)).proof;
    const key = await crypto.subtle.importKey(
      "raw",
      new TextEncoder().encode(token),
      { name: "HMAC", hash: "SHA-256" },
      false,
      ["sign"],
    );
    const signature = new Uint8Array(
      await crypto.subtle.sign(
        "HMAC",
        key,
        new TextEncoder().encode(`jarvis-health:${port}:${nonce}`),
      ),
    );
    const expected = Array.from(signature, (x) =>
      x.toString(16).padStart(2, "0"),
    ).join("");
    let difference = 0;
    if (typeof proof !== "string" || proof.length !== expected.length)
      throw new Error("Local service verification failed.");
    for (let i = 0; i < expected.length; i++)
      difference |= expected.charCodeAt(i) ^ proof.charCodeAt(i);
    if (difference) throw new Error("Local service verification failed.");
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener("abort", abort);
  }
  const headers = new Headers(options.headers);
  headers.set("Authorization", "Bearer " + token);
  return fetcher(path, {
    ...options,
    headers,
    redirect: "error",
    cache: "no-store",
  });
}
