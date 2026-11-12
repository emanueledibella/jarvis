export type Authorization = { name: string; url: string; expires_in: number };

export function validAuthorizations(value: unknown): Authorization[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is Authorization => {
    if (!item || typeof item.name !== "string" || !item.name || item.name.length > 128 ||
        typeof item.url !== "string" || item.url.length > 16_384 ||
        !Number.isFinite(item.expires_in) || item.expires_in <= 0 || item.expires_in > 180) return false;
    try {
      const url = new URL(item.url);
      return url.protocol === "https:" && !url.username && !url.password;
    } catch { return false; }
  }).slice(0, 10);
}
