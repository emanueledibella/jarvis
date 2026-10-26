import italian from "./locales/it.json" with { type: "json" };

export type InterfaceLanguage = "en" | "it";
const messages: Readonly<Record<string, string>> = italian;
const storageKey = "jarvis-ui-language";
const listeners = new Set<() => void>();

export function isInterfaceLanguage(
  value: unknown,
): value is InterfaceLanguage {
  return value === "en" || value === "it";
}

function initialLanguage(): InterfaceLanguage {
  try {
    const saved = globalThis.localStorage?.getItem(storageKey);
    return isInterfaceLanguage(saved) ? saved : "en";
  } catch {
    return "en";
  }
}

let language: InterfaceLanguage = initialLanguage();
export const getInterfaceLanguage = () => language;
export const uiLocale = () => (language === "it" ? "it-IT" : "en-GB");

export function subscribeLanguage(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function setInterfaceLanguage(value: InterfaceLanguage) {
  if (!isInterfaceLanguage(value))
    throw new Error("Unsupported interface language.");
  const changed = language !== value;
  language = value;
  try {
    globalThis.localStorage?.setItem(storageKey, value);
  } catch {
    /* Storage is optional. */
  }
  if (typeof document !== "undefined") document.documentElement.lang = value;
  if (changed) listeners.forEach((listener) => listener());
}

export function translate(
  source: string,
  selected: InterfaceLanguage,
  values: Record<string, string | number> = {},
): string {
  const key = source.trim();
  const text =
    selected === "it" && Object.hasOwn(messages, key)
      ? source.slice(0, source.indexOf(key)) +
        messages[key] +
        source.slice(source.indexOf(key) + key.length)
      : source;
  return text.replace(
    /\{([a-zA-Z][a-zA-Z0-9_]*)\}/g,
    (original, name: string) => {
      if (!Object.hasOwn(values, name)) return original;
      const value = values[name];
      return typeof value === "number"
        ? new Intl.NumberFormat(selected === "it" ? "it-IT" : "en-GB").format(
            value,
          )
        : value;
    },
  );
}

export function t(
  source: string,
  values: Record<string, string | number> = {},
) {
  if (!source) return source;
  const unavailable = /^Service unavailable \((\d+)\)\.$/.exec(source);
  if (unavailable)
    return translate("Service unavailable ({status}).", language, {
      status: unavailable[1],
    });
  if (source.startsWith("Invalid fields: ")) {
    return translate("Invalid fields: {fields}", language, {
      fields: source.slice(16),
    });
  }
  return translate(source, language, values);
}

export function formatNumber(value: number, digits = 0) {
  return new Intl.NumberFormat(uiLocale(), {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}
