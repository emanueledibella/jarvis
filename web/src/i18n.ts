import { useSyncExternalStore } from "react";
import { api, hasToken, patch } from "./api";
import {
  getInterfaceLanguage,
  isInterfaceLanguage,
  setInterfaceLanguage,
  subscribeLanguage,
  type InterfaceLanguage,
} from "./localization";

export { t, uiLocale, formatNumber } from "./localization";

export function useI18n() {
  return useSyncExternalStore(
    subscribeLanguage,
    getInterfaceLanguage,
    getInterfaceLanguage,
  );
}

let revision = 0;
let saving = 0;
export async function syncInterfaceLanguage() {
  if (!hasToken() || saving) return;
  const started = revision;
  const data = await api("/settings");
  if (
    started === revision &&
    !saving &&
    isInterfaceLanguage(data.values.ui_language)
  ) {
    setInterfaceLanguage(data.values.ui_language);
  }
}

export async function saveInterfaceLanguage(selected: InterfaceLanguage) {
  if (!isInterfaceLanguage(selected))
    throw new Error("Unsupported interface language.");
  const previous = getInterfaceLanguage();
  const started = ++revision;
  saving += 1;
  setInterfaceLanguage(selected);
  try {
    const result = await patch("/settings", { ui_language: selected });
    if (!isInterfaceLanguage(result.values.ui_language))
      throw new Error("Unsupported interface language.");
    if (started === revision) setInterfaceLanguage(result.values.ui_language);
    return result;
  } catch (error) {
    if (started === revision) setInterfaceLanguage(previous);
    throw error;
  } finally {
    saving -= 1;
  }
}
