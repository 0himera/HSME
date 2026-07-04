"use client";

import { useEffect, useRef, useState } from "react";
import { ROLES, type Statistics, type UserSession } from "@/lib/types";
import { Icon, TickNumber } from "./ui";

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

  useEffect(() => {
    const close = (ev: MouseEvent) => {
      if (!menuRef.current?.contains(ev.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

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
          гиперграфовая научная память R&amp;D
        </span>
      </div>

      <div className="flex items-center gap-3">
        {stats && (
          <span className="chip mono !text-[11px] text-ink2 hidden md:inline-flex">
            <span
              className={`w-1.5 h-1.5 rounded-full ${
                live ? "bg-malachite" : "bg-sulfur"
              } a-pulse`}
            />
            <TickNumber value={stats.total_experiments} /> гиперрёбер
          </span>
        )}

        <div className="relative" ref={menuRef}>
          <button
            className="chip !py-1.5"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
          >
            <Icon name="user" size={13} className="text-nickel" />
            <span>
              {currentRole?.label} · {user.name}
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
            <div className="absolute right-0 top-[calc(100%+6px)] w-60 card !bg-card2 p-1.5 a-slide-up z-50 shadow-[0_10px_36px_rgba(0,0,0,.5)]">
              <p className="lbl px-2.5 pt-1.5 pb-1">Активная роль</p>
              {ROLES.map((r) => (
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
                    {r.label}
                    <span className="block text-[11px] text-ink3">
                      {r.person}
                    </span>
                  </span>
                  {r.id === user.role && <Icon name="check" size={13} />}
                </button>
              ))}
              <p className="px-2.5 py-2 text-[10.5px] text-ink3 border-t border-line mt-1.5 flex items-center gap-1.5">
                <Icon name="lock" size={11} />
                роль передаётся ядру в заголовках запроса
              </p>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
