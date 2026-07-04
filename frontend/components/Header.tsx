"use client";

import { useEffect, useRef, useState } from "react";
import { ROLES, type Statistics, type UserSession } from "@/lib/types";
import { Icon, TickNumber } from "./ui";
import { useLang } from "@/lib/i18n";

// ── Sun / Moon icons ──────────────────────────────────────────────────────────
function SunIcon({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none"
      stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="8" cy="8" r="2.8" />
      <path d="M8 1.5v1.8M8 12.7v1.8M1.5 8h1.8M12.7 8h1.8M3.6 3.6l1.27 1.27M11.13 11.13l1.27 1.27M12.4 3.6l-1.27 1.27M4.87 11.13l-1.27 1.27" />
    </svg>
  );
}

function MoonIcon({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none"
      stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M13.5 9.5A6 6 0 0 1 6.5 2.5a5.5 5.5 0 1 0 7 7Z" />
    </svg>
  );
}

// ── Локализованные метки ролей ─────────────────────────────────────────────────
const ROLE_LABEL_KEYS = {
  Administrator: "role_admin",
  Analyst: "role_analyst",
  Researcher: "role_researcher",
  "External Partner": "role_partner",
} as const;

export default function Header({
  user,
  onUserChange,
  stats,
  live,
}: {
  user: UserSession;
  onUserChange: (u: UserSession) => void;
  stats: Statistics | null;
  live: boolean;
}) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const currentRole = ROLES.find((r) => r.id === user.role);
  const { t, lang, setLang, theme, setTheme } = useLang();

  useEffect(() => {
    const close = (ev: MouseEvent) => {
      if (!menuRef.current?.contains(ev.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const roleLabel = currentRole
    ? t(ROLE_LABEL_KEYS[currentRole.id as keyof typeof ROLE_LABEL_KEYS] ?? "role_analyst")
    : "";

  return (
    <header className="relative z-10 flex items-center justify-between px-5 h-[54px] bg-panel border-b border-line shrink-0">
      <div
        className="absolute inset-x-0 top-0 h-px"
        style={{
          background:
            "linear-gradient(90deg, transparent, rgba(201,138,82,.45) 30%, rgba(201,138,82,.45) 70%, transparent)",
        }}
        aria-hidden="true"
      />
      <div className="flex items-baseline gap-3 select-none">
        <span className="serif text-[19px] font-medium tracking-wide">
          HSME
        </span>
        <span className="text-[11.5px] text-ink3 hidden sm:inline">
          {t("header_subtitle")}
        </span>
      </div>

      <div className="flex items-center gap-2">
        {stats && (
          <span className="chip mono !text-[11px] text-ink2 hidden md:inline-flex">
            <span
              className={`w-1.5 h-1.5 rounded-full ${
                live ? "bg-malachite" : "bg-sulfur"
              } a-pulse`}
            />
            <TickNumber value={stats.total_experiments} />
            {" "}{t("header_edges")}
          </span>
        )}

        {/* Theme toggle */}
        <button
          className="chip !py-1.5 !px-2.5"
          onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          aria-label={theme === "dark" ? t("header_theme_toggle_light") : t("header_theme_toggle_dark")}
          title={theme === "dark" ? t("header_theme_toggle_light") : t("header_theme_toggle_dark")}
        >
          {theme === "dark" ? <SunIcon size={13} /> : <MoonIcon size={13} />}
        </button>

        {/* Lang toggle */}
        <button
          className="chip !py-1 !px-2.5 mono !text-[11px] font-medium"
          onClick={() => setLang(lang === "ru" ? "en" : "ru")}
          aria-label={t("header_lang_toggle")}
        >
          {t("header_lang_toggle")}
        </button>

        <div className="relative" ref={menuRef}>
          <button
            className="chip !py-1.5"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
          >
            <Icon name="user" size={13} className="text-nickel" />
            <span>
              {roleLabel} · {user.name}
            </span>
            <Icon
              name="chevron"
              size={12}
              className={`transition-transform duration-200 ${
                open ? "rotate-180" : ""
              }`}
            />
          </button>

          {open && (
            <div className="absolute right-0 top-[calc(100%+6px)] w-60 card !bg-card2 p-1.5 a-slide-up z-50 shadow-[0_10px_36px_rgba(0,0,0,.3)]">
              <p className="lbl px-2.5 pt-1.5 pb-1">{t("header_role_label")}</p>
              {ROLES.map((r) => {
                const rLabel = t(ROLE_LABEL_KEYS[r.id as keyof typeof ROLE_LABEL_KEYS]);
                return (
                  <button
                    key={r.id}
                    className={`w-full text-left px-2.5 py-2 rounded-lg text-[12.5px] flex items-center justify-between transition-colors ${
                      r.id === user.role
                        ? "bg-coppertint text-copperbright"
                        : "text-ink2 hover:bg-panel2 hover:text-ink"
                    }`}
                    onClick={() => {
                      onUserChange({ name: r.person, role: r.id });
                      setOpen(false);
                    }}
                  >
                    <span>
                      {rLabel}
                      <span className="block text-[11px] text-ink3">
                        {r.person}
                      </span>
                    </span>
                    {r.id === user.role && <Icon name="check" size={13} />}
                  </button>
                );
              })}
              <p className="px-2.5 py-2 text-[10.5px] text-ink3 border-t border-line mt-1.5 flex items-center gap-1.5">
                <Icon name="lock" size={11} />
                {t("header_role_note")}
              </p>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
