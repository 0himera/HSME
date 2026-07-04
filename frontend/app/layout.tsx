import type { Metadata } from "next";
import "./fonts.css";
import "./globals.css";
import CursorFX from "@/components/CursorFX";
import LangProvider from "@/lib/LangProvider";

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
    <html lang="ru" data-theme="dark" className="h-full antialiased" suppressHydrationWarning>
      <body className="h-full">
        <LangProvider>
          <div className="furnace-glow" aria-hidden="true" />
          {children}
          <div className="grain" aria-hidden="true" />
          <CursorFX />
        </LangProvider>
      </body>
    </html>
  );
}
