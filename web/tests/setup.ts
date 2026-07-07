import * as React from "react";
import { vi } from "vitest";
import "@testing-library/jest-dom/vitest";

/**
 * next/link is replaced with a plain anchor so jsdom can resolve
 * the href without booting the Next.js runtime. The original
 * ``Link`` accepts ``className`` + child React tree; the shim
 * forwards both to ``<a>`` so role-based queries still find the
 * rendered nav cards.
 */
vi.mock("next/link", () => ({
  default: ({
    children,
    href,
    className,
  }: {
    children: React.ReactNode;
    href: string;
    className?: string;
  }) => React.createElement("a", { href, className }, children),
}));

/**
 * next/font/google Google Fonts are a build-time download. jsdom has
 * no network access during tests and the font binary is irrelevant
 * to layout assertions; return inert CSS variable shims so the
 * ``className`` template literal in :file:`app/layout.tsx` still
 * types + renders.
 */
vi.mock("next/font/google", () => ({
  Geist: () => ({ variable: "--mock-sans", className: "mock-sans" }),
  Geist_Mono: () => ({ variable: "--mock-mono", className: "mock-mono" }),
}));

/**
 * @/lib/env reads ``process.env.API_BASE_URL`` at module-load. The
 * Server Components under test need a deterministic value (``http://test/api``)
 * so footer / display-URL assertions are stable across machines.
 * ``displayedApiBaseUrl`` is aliased to the same constant since
 * :file:`lib/env.ts` documents it as a derived-but-stable symbol.
 */
const API_BASE_URL = "http://test/api";
vi.mock("@/lib/env", () => ({
  API_BASE_URL,
  displayedApiBaseUrl: API_BASE_URL,
}));
