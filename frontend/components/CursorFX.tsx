"use client";

import { useEffect, useRef } from "react";

const INTERACTIVE =
  'a, button, [role="button"], label, [data-cursor="pointer"], select, summary';
const TEXTUAL = 'input, textarea, [contenteditable="true"], [data-cursor="text"]';

export default function CursorFX() {
  const dotRef = useRef<HTMLDivElement>(null);
  const ringRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (window.matchMedia("(pointer: coarse)").matches) return;

    const dot = dotRef.current!;
    const ring = ringRef.current!;
    let mx = -100;
    let my = -100;
    let rx = -100;
    let ry = -100;
    let raf = 0;
    let visible = false;

    const onMove = (ev: MouseEvent) => {
      mx = ev.clientX;
      my = ev.clientY;
      if (!visible) {
        visible = true;
        rx = mx;
        ry = my;
        document.body.classList.add("cur-visible");
      }
      const t = ev.target instanceof Element ? ev.target : null;
      const isText = !!t?.closest(TEXTUAL);
      const isPointer = !isText && !!t?.closest(INTERACTIVE);
      document.body.classList.toggle("cur-hover", isPointer);
      document.body.classList.toggle("cur-text", isText);
    };

    const onDown = () => document.body.classList.add("cur-down");
    const onUp = () => document.body.classList.remove("cur-down");
    const onLeave = () => {
      visible = false;
      document.body.classList.remove("cur-visible");
    };

    const loop = () => {
      rx += (mx - rx) * 0.16;
      ry += (my - ry) * 0.16;
      dot.style.transform = `translate(${mx}px, ${my}px)`;
      ring.style.transform = `translate(${rx}px, ${ry}px)`;
      raf = requestAnimationFrame(loop);
    };

    window.addEventListener("mousemove", onMove, { passive: true });
    window.addEventListener("mousedown", onDown);
    window.addEventListener("mouseup", onUp);
    document.documentElement.addEventListener("mouseleave", onLeave);
    raf = requestAnimationFrame(loop);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("mouseup", onUp);
      document.documentElement.removeEventListener("mouseleave", onLeave);
      document.body.classList.remove(
        "cur-visible",
        "cur-hover",
        "cur-text",
        "cur-down",
      );
    };
  }, []);

  return (
    <>
      <div ref={ringRef} className="cur-ring" aria-hidden="true" />
      <div ref={dotRef} className="cur-dot" aria-hidden="true" />
    </>
  );
}
