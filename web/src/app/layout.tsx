import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { PlayerSearchBar } from "@/components/PlayerSearchBar";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "GW2Analytics",
  description:
    "Independent WvW combat analytics for Guild Wars 2. Local .zevtc parsing, world enrichment, multi-fight rollups.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable}`}>
      <body>
        {/*
          v0.7.1 of web: a sticky header bar hosts the global
          player search affordance (the :class:`PlayerSearchBar`)
          so the analyst can pivot to a player profile from any
          page. The header is a Server Component (renders the
          Client Component sub-view); the sticky position keeps
          the search input always-visible on long-scroll pages
          (the /fights/[id] drill-down can be 100+ buckets at
          window_s=1). The bar's background + border pick up
          the canonical --surface / --border tokens so the
          header sits inside the existing dark theme.
        */}
        <header
          style={{
            position: "sticky",
            top: 0,
            zIndex: 10,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "12px 32px",
            background: "var(--surface)",
            borderBottom: "1px solid var(--border)",
            gap: 16,
            flexWrap: "wrap",
          }}
        >
          <a
            href="/"
            style={{
              fontSize: 14,
              fontWeight: 600,
              color: "var(--accent)",
              textDecoration: "none",
            }}
          >
            GW2Analytics
          </a>
          <PlayerSearchBar />
        </header>
        {children}
      </body>
    </html>
  );
}
