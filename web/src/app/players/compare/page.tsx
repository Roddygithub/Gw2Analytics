/**
 * v0.10.0 plan 032: ``/players/compare`` page.
 *
 * Server Component that fetches the v0.10.0-api
 * ``GET /api/v1/players/compare/timeline`` payload on the
 * server so the chart is visible at first paint and the
 * URL is permalinkable. The Client Component
 * (:class:`CrossAccountCompareSection`) owns the
 * metric / scale / bucket / tz toggles.
 *
 * URL surface
 * ===========
 * ``/players/compare?accounts=A&accounts=B`` -- a
 * repeatable ``accounts`` query param, matching the
 * gateway's ``GET /api/v1/players/compare/timeline`` route
 * exactly. The page is invalid (shows the empty-state
 * panel) when:
 *
 * - no ``?accounts=`` in URL: 0 unique accounts.
 * - 1 ``?accounts=`` in URL: 1 unique account (the route
 *   enforces ``min_length=2`` so the gateway returns 422,
 *   which we render as the upstream-error card).
 * - 5+ ``?accounts=`` in URL: 5+ unique accounts (the
 *   route enforces ``max_length=4``).
 *
 * The 422 / network-error paths render the same
 * upstream-error card pattern the existing per-account
 * page uses (:class:`PlayerProfilePage`).
 *
 * Why a Server Component
 * ======================
 * Same rationale as :class:`PlayerProfilePage`: the
 * gateway's roll-up is server-side state, the URL is
 * permalinkable (so the analyst can share a specific
 * comparison), and the SSR-first pattern keeps the
 * first-paint waterfall tight.
 *
 * Force-dynamic
 * =============
 * ``export const dynamic = "force-dynamic"`` opts out of
 * Next.js's static caching so the comparison reflects the
 * latest parsed fight state on every request.
 */

import {
  fetchPlayerCompareTimeline,
  formatApiError,
} from "@/lib/api";
import { CrossAccountCompareSection } from "@/components/CrossAccountCompareSection";

export const dynamic = "force-dynamic";

const MIN_ACCOUNTS = 2;
const MAX_ACCOUNTS = 4;

const EMPTY_STYLE: React.CSSProperties = {
  padding: "12px 16px",
  border: "1px solid var(--border)",
  borderRadius: 4,
  color: "var(--foreground)",
  opacity: 0.7,
  fontSize: 14,
  fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
};

const HINT_STYLE: React.CSSProperties = {
  fontSize: 13,
  opacity: 0.7,
  fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
};

export default async function ComparePage(props: {
  searchParams: Promise<{ accounts?: string | string[] }>;
}) {
  const sp = await props.searchParams;
  // Next.js delivers ``?accounts=A&accounts=B`` as
  // ``["A", "B"]``. A single ``?accounts=A`` lands as a
  // string. We normalise to ``string[]`` here so the
  // dedupe + min-length check below has a single code
  // path.
  const rawAccounts = sp.accounts
    ? Array.isArray(sp.accounts)
      ? sp.accounts
      : [sp.accounts]
    : [];
  // Dedupe in first-seen order (matches the route's
  // dedupe contract). An empty / single-account
  // request renders the empty-state panel; a 5+ request
  // surfaces the upstream-error card.
  const seen = new Set<string>();
  const accounts: string[] = [];
  for (const a of rawAccounts) {
    const trimmed = a.trim();
    if (!trimmed) continue;
    if (!seen.has(trimmed)) {
      seen.add(trimmed);
      accounts.push(trimmed);
    }
  }

  if (accounts.length < MIN_ACCOUNTS) {
    return (
      <main
        style={{
          padding: "32px",
          display: "flex",
          flexDirection: "column",
          gap: "24px",
          width: "100%",
        }}
      >
        <header>
          <p style={{ marginBottom: 8 }}>
            <a
              href="/players"
              style={{
                color: "var(--accent)",
                fontSize: 13,
                textDecoration: "none",
              }}
            >
              &larr; Back to players
            </a>
          </p>
          <h1 style={{ fontSize: 28, marginBottom: 4 }}>
            Compare accounts
          </h1>
          <p style={{ opacity: 0.7 }}>
            Overlay 2-4 accounts&apos; damage, healing, and
            buff-removal curves on a single chart.
          </p>
        </header>
        <div style={EMPTY_STYLE}>
          Add at least 2 accounts via the URL:{" "}
          <code style={{ fontFamily: "var(--font-geist-mono), ui-monospace, monospace" }}>
            /players/compare?accounts=A&amp;accounts=B
          </code>
          . The page accepts up to {MAX_ACCOUNTS} accounts.
        </div>
        <p style={HINT_STYLE}>
          Tip: open a player profile, copy the
          <code> account_name</code>, and append it as an{" "}
          <code>&amp;accounts=</code> query param.
        </p>
      </main>
    );
  }

  if (accounts.length > MAX_ACCOUNTS) {
    return (
      <main
        style={{
          padding: "32px",
          display: "flex",
          flexDirection: "column",
          gap: "24px",
          width: "100%",
        }}
      >
        <header>
          <p style={{ marginBottom: 8 }}>
            <a
              href="/players"
              style={{
                color: "var(--accent)",
                fontSize: 13,
                textDecoration: "none",
              }}
            >
              &larr; Back to players
            </a>
          </p>
          <h1 style={{ fontSize: 28, marginBottom: 4 }}>
            Compare accounts
          </h1>
        </header>
        <p style={{ color: "var(--accent)" }}>
          Too many accounts: got {accounts.length}, max is{" "}
          {MAX_ACCOUNTS}. Remove{" "}
          {accounts.length - MAX_ACCOUNTS} from the URL.
        </p>
      </main>
    );
  }

  let series: Awaited<
    ReturnType<typeof fetchPlayerCompareTimeline>
  > = [];
  let fetchError: string | null = null;
  try {
    series = await fetchPlayerCompareTimeline(accounts, {
      bucket: "day",
      tz: "UTC",
    });
  } catch (err) {
    fetchError = formatApiError(err);
  }

  if (fetchError) {
    return (
      <main
        style={{
          padding: "32px",
          display: "flex",
          flexDirection: "column",
          gap: "24px",
          width: "100%",
        }}
      >
        <header>
          <p style={{ marginBottom: 8 }}>
            <a
              href="/players"
              style={{
                color: "var(--accent)",
                fontSize: 13,
                textDecoration: "none",
              }}
            >
              &larr; Back to players
            </a>
          </p>
          <h1 style={{ fontSize: 28, marginBottom: 4 }}>
            Compare accounts
          </h1>
        </header>
        <p style={{ color: "var(--accent)" }}>{fetchError}</p>
      </main>
    );
  }

  return (
    <main
      style={{
        padding: "32px",
        display: "flex",
        flexDirection: "column",
        gap: "24px",
        width: "100%",
      }}
    >
      <header>
        <p style={{ marginBottom: 8 }}>
          <a
            href="/players"
            style={{
              color: "var(--accent)",
              fontSize: 13,
              textDecoration: "none",
            }}
          >
            &larr; Back to players
          </a>
        </p>
        <h1 style={{ fontSize: 28, marginBottom: 4 }}>
          Compare accounts
        </h1>
        <p
          style={{
            opacity: 0.7,
            fontFamily: "var(--font-geist-mono), ui-monospace, monospace",
          }}
        >
          {accounts.join(" · ")}
        </p>
      </header>

      <CrossAccountCompareSection
        initialAccounts={accounts}
        initialSeries={series}
        initialBucket="day"
        initialTz="UTC"
      />
    </main>
  );
}
