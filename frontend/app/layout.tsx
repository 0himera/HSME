import type { Metadata } from "next";
import "./fonts.css";
import "./globals.css";
import CursorFX from "@/components/CursorFX";

export const metadata: Metadata = {
  title: "HSME — научная память R&D",
  description:
    "HyperGraph Research Memory Engine — карта знаний R&D горно-металлургической отрасли",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ru" className="h-full antialiased">
      <body className="h-full">
        <div className="furnace-glow" aria-hidden="true" />
        {children}
        <div className="grain" aria-hidden="true" />
        <CursorFX />
      </body>
    </html>
  );
}
