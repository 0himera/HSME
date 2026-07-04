"use client";

import {
  createContext,
  useCallback,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import type { Lang } from "./i18n";

interface LangCtx {
  lang: Lang;
  setLang: (l: Lang) => void;
  theme: "dark" | "light";
  setTheme: (t: "dark" | "light") => void;
}

export const LangContext = createContext<LangCtx | null>(null);

const LS_LANG = "hsme:lang";
const LS_THEME = "hsme:theme";

function readLS<T extends string>(key: string, fallback: T, allowed: T[]): T {
  if (typeof window === "undefined") return fallback;
  const v = localStorage.getItem(key) as T | null;
  return v && allowed.includes(v) ? v : fallback;
}

export default function LangProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>("ru");
  const [theme, setThemeState] = useState<"dark" | "light">("dark");
  const [mounted, setMounted] = useState(false);

  // Read from localStorage after mount (avoid SSR mismatch)
  useEffect(() => {
    const savedLang = readLS<Lang>(LS_LANG, "ru", ["ru", "en"]);
    const savedTheme = readLS<"dark" | "light">(LS_THEME, "dark", [
      "dark",
      "light",
    ]);
    setLangState(savedLang);
    setThemeState(savedTheme);
    setMounted(true);
  }, []);

  // Apply theme to <html> data-theme attribute
  useEffect(() => {
    if (!mounted) return;
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem(LS_THEME, theme);
  }, [theme, mounted]);

  // Persist lang
  useEffect(() => {
    if (!mounted) return;
    localStorage.setItem(LS_LANG, lang);
    document.documentElement.setAttribute("lang", lang);
  }, [lang, mounted]);

  const setLang = useCallback((l: Lang) => setLangState(l), []);
  const setTheme = useCallback((t: "dark" | "light") => setThemeState(t), []);

  return (
    <LangContext.Provider value={{ lang, setLang, theme, setTheme }}>
      {children}
    </LangContext.Provider>
  );
}
