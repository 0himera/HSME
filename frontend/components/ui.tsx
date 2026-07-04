"use client";

import { useEffect, useRef, useState } from "react";

/** Число, «натикивающее» от 0 до value при появлении. */
export function TickNumber({
  value,
  duration = 700,
  className = "",
  locale = "ru-RU",
}: {
  value: number;
  duration?: number;
  className?: string;
  locale?: string;
}) {
  const [shown, setShown] = useState(0);
  const prev = useRef(0);

  useEffect(() => {
    const from = prev.current;
    prev.current = value;
    const start = performance.now();
    let raf = 0;
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      setShown(Math.round(from + (value - from) * eased));
      if (t < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [value, duration]);

  return <span className={className}>{shown.toLocaleString(locale)}</span>;
}

export function Icon({
  name,
  size = 14,
  className = "",
}: {
  name:
    | "arrow-up"
    | "arrow-left"
    | "search"
    | "lock"
    | "pin"
    | "copy"
    | "check"
    | "x"
    | "chevron"
    | "diff"
    | "grid"
    | "graph"
    | "file"
    | "flask"
    | "user";
  size?: number;
  className?: string;
}) {
  const paths: Record<string, React.ReactNode> = {
    "arrow-up": <path d="M8 13V3m0 0L3.5 7.5M8 3l4.5 4.5" />,
    "arrow-left": <path d="M13 8H3m0 0l4.5 4.5M3 8l4.5-4.5" />,
    search: (
      <>
        <circle cx="7" cy="7" r="4.5" />
        <path d="M10.5 10.5L14 14" />
      </>
    ),
    lock: (
      <>
        <rect x="3.5" y="7" width="9" height="6.5" rx="1.5" />
        <path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" />
      </>
    ),
    pin: <path d="M6 2.5h4l.5 5 2 2h-9l2-2 .5-5ZM8 9.5V14" />,
    copy: (
      <>
        <rect x="5.5" y="5.5" width="8" height="8" rx="1.5" />
        <path d="M10.5 5.5v-2a1 1 0 0 0-1-1h-6a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2" />
      </>
    ),
    check: <path d="M3 8.5L6.5 12L13 4.5" />,
    x: <path d="M4 4l8 8M12 4l-8 8" />,
    chevron: <path d="M4.5 6.5L8 10l3.5-3.5" />,
    diff: (
      <>
        <path d="M5 3v10M5 3L2.5 5.5M5 3l2.5 2.5" />
        <path d="M11 13V3M11 13l-2.5-2.5M11 13l2.5-2.5" />
      </>
    ),
    grid: (
      <>
        <rect x="2.5" y="2.5" width="4.6" height="4.6" rx="1" />
        <rect x="8.9" y="2.5" width="4.6" height="4.6" rx="1" />
        <rect x="2.5" y="8.9" width="4.6" height="4.6" rx="1" />
        <path d="M11.2 9.5v4M9.2 11.5h4" />
      </>
    ),
    graph: (
      <>
        <circle cx="4" cy="12" r="1.8" />
        <circle cx="8" cy="4" r="1.8" />
        <circle cx="12.5" cy="10.5" r="1.8" />
        <path d="M5.2 10.6L7 5.6M9.6 5.2l2 3.8M5.8 12l4.9-.9" />
      </>
    ),
    file: (
      <>
        <path d="M4 2h5.5L13 5.5V14H4V2Z" />
        <path d="M9.5 2v3.5H13" />
      </>
    ),
    flask: (
      <>
        <path d="M6.5 2h3M7 2v4.5L3.5 12a1.6 1.6 0 0 0 1.4 2.5h6.2a1.6 1.6 0 0 0 1.4-2.5L9 6.5V2" />
        <path d="M5 10.5h6" />
      </>
    ),
    user: (
      <>
        <circle cx="8" cy="5.5" r="2.7" />
        <path d="M2.8 14a5.2 5.2 0 0 1 10.4 0" />
      </>
    ),
  };

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.3"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      {paths[name]}
    </svg>
  );
}

/** Метка панели в стиле техдокументации. */
export function PanelLabel({ children }: { children: React.ReactNode }) {
  return <p className="lbl mb-2.5 select-none">{children}</p>;
}
