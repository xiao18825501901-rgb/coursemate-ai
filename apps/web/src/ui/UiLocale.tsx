import { createInstance } from "i18next";
import { createContext, useCallback, useContext, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { I18nextProvider } from "react-i18next";
import zh from "./locales/zh-CN.json";
import en from "./locales/en.json";

type Locale = "zh-CN" | "en";
type Params = Record<string, string | number>;
const supported = (value: unknown): value is Locale => value === "zh-CN" || value === "en";
const preferenceKey = (owner: string | null) => `coursejesus:ui-locale:${encodeURIComponent(owner || "guest")}`;

function restore(owner: string | null, serverPreference?: unknown): Locale {
  if (supported(serverPreference)) return serverPreference;
  try {
    const cached = localStorage.getItem(preferenceKey(owner));
    if (supported(cached)) return cached;
  } catch { /* Storage may be disabled; UI locale is still usable. */ }
  return "zh-CN";
}

function instance() {
  const result = createInstance();
  void result.init({ resources: { "zh-CN": { translation: zh }, en: { translation: en } },
    lng: "zh-CN", fallbackLng: "zh-CN", supportedLngs: ["zh-CN", "en"],
    initAsync: false, interpolation: { escapeValue: false }, returnNull: false });
  return result;
}

const fallback = instance();
export const defaultUiTranslate = (key: string, params: Params = {}): string =>
  String(fallback.t(key, params));

interface UiLocaleValue {
  locale: Locale;
  t: (key: string, params?: Params) => string;
  setLocale: (locale: Locale) => void;
  setOwner: (owner: string | null, serverPreference?: unknown) => void;
}

export const UiLocaleContext = createContext<UiLocaleValue>({ locale: "zh-CN",
  t: defaultUiTranslate, setLocale: () => undefined, setOwner: () => undefined });

/** UI-only state: no lesson/session/prompt fields or model/API calls here. */
export function UiLocaleProvider({ children }: { children: ReactNode }) {
  const [i18n] = useState(instance);
  const owner = useRef<string | null>(null);
  const [locale, updateLocale] = useState<Locale>(() => restore(null));
  const setOwner = useCallback((nextOwner: string | null, serverPreference?: unknown) => {
    owner.current = nextOwner;
    updateLocale(restore(nextOwner, serverPreference));
  }, []);
  const setLocale = useCallback((next: Locale) => {
    if (!supported(next)) throw new Error("UNSUPPORTED_UI_LOCALE");
    updateLocale(next);
    try { localStorage.setItem(preferenceKey(owner.current), next); } catch { /* Non-fatal. */ }
  }, []);
  useLayoutEffect(() => {
    void i18n.changeLanguage(locale);
    document.documentElement.lang = locale;
  }, [i18n, locale]);
  const value = useMemo<UiLocaleValue>(() => ({ locale, setLocale, setOwner,
    t: (key, params = {}) => String(i18n.getFixedT(locale)(key, params)) }),
    [i18n, locale, setLocale, setOwner]);
  return <I18nextProvider i18n={i18n}><UiLocaleContext.Provider value={value}>
    {children}
  </UiLocaleContext.Provider></I18nextProvider>;
}

export function LanguageControl() {
  const { locale, setLocale, t } = useContext(UiLocaleContext);
  return <div className="cj-language-control" role="group"
    aria-label={t("dashboard.interfaceLanguage")} title={t("dashboard.languageNotice")}>
    {(["zh-CN", "en"] as const).map(option => <button type="button" key={option}
      lang={option} aria-pressed={locale === option} onClick={() => setLocale(option)}>
      {option === "zh-CN" ? "中文" : "English"}
    </button>)}
  </div>;
}

function flatten(value: object, prefix = ""): Record<string, string> {
  return Object.entries(value).reduce<Record<string, string>>((result, [key, entry]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof entry === "string") result[path] = entry;
    else Object.assign(result, flatten(entry, path));
    return result;
  }, {});
}

export function dictionaryParity(): string[] {
  const a = flatten(zh), b = flatten(en);
  const placeholders = (text: string) => [...text.matchAll(/\{\{([A-Za-z][A-Za-z0-9_]*)\}\}/g)]
    .map(match => match[1]).sort();
  return [...new Set([...Object.keys(a), ...Object.keys(b)])].filter(key =>
    !(key in a) || !(key in b) ||
    JSON.stringify(placeholders(a[key]!)) !== JSON.stringify(placeholders(b[key]!)));
}
