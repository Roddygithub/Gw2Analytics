/**
 * Server Component that fetches the v0.7.0-api
 * ``GET /api/v1/players`` paginated roll-up and renders an AG
 * Grid on the client.
 *
 * Why a Server Component
 * ======================
 * The data source is the gateway's cross-fight roll-up
 * (Postgres-backed for the per-fight agents table, with the
 * per-fight contribution computation in
 * :func:`apps.api.routes.players._compute_contributions`).
 * Server-side fetch avoids the client-side waterfall and
 * ensures the initial response is fully populated.
 *
 * Force-dynamic
 * =============
 * ``export const dynamic = "force-dynamic"`` opts out of
 * Next.js's static caching so the list reflects the latest
 * parsed fight state on every request. The endpoint is
 * paginated server-side so we don't page through the roll-up
 * here.
 *
 * Empty + 404 + upstream-error handling
 * =====================================
 * - empty list (``players == []``) -> the
 *   :class:`PlayersGrid` renders a styled "no rows" panel.
 * - ``ApiError(404, ...)`` from the gateway -> the page
 *   renders an upstream-error card with the gateway's error
 *   body. The page does NOT raise 404 itself; the canonical
 *   404 lives at the API boundary, and the analyst surface
 *   just shows the upstream message.
 * - any other thrown error (network, 5xx) -> the same
 *   upstream-error card with the error message.
 */

import { fetchPlayers, formatApiError, type PlayerListRow } from "@/lib/api";
import { PlayersGrid } from "@/components/PlayersGrid";
import { ProfessionFilter } from "@/components/ProfessionFilter";

function CompareCta({ rows }: { rows: PlayerListRow[] }) {
  if (rows.length < 2) {
    return null;
  }
  const a = rows[0];
  const b = rows[1];
  if (!a || !b) {
    return null;
  }
  const href =
    `/players/compare?accounts=${encodeURIComponent(a.account_name)}` +
    `&accounts=${encodeURIComponent(b.account_name)}`;
  return (
    // 2026-07-16 mobile+a11y audit P1: touch-target bump from
    //   ~24px to ~44px (WCAG 2.5.8). The new padding
    //   ``14px 16px`` + fontSize 14 hit the canonical 44x44
    //   minimum bounding box for a text-only link on a
    //   mobile browser (the link is still rendered as an
    //   <a> with no fixed height so the padding fully
    //   drives the hit area on every viewport).
    <a
      href={href}
      style={{
        alignSelf: "flex-start",
        padding: "14px 16px",
        fontSize: 14,
        border: "1px solid var(--accent)",
        borderRadius: 4,
        color: "var(--accent)",
        textDecoration: "none",
        fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
      }}
    >
      Compare the first 2 players &rarr;
    </a>
  );
}

export const dynamic = "force-dynamic";

/**
 * v0.9.0 of the page: the page is now async + accepts
 * ``searchParams`` so the ``?profession=`` filter flows from
 * the URL to the gateway without a client-side round-trip
 * on the first paint.
 *
 * Next.js 15+ delivers ``searchParams`` as a ``Promise``
 * (matches the ``params`` async contract documented in
 * :mod:`web/src/lib/api.ts`); the page awaits it BEFORE
 * forwarding the value to ``fetchPlayers``. An invalid
 * ``?profession=`` value surfaces as 422 from the
 * gateway's :class:`Profession` enum validation, and the
 * existing ``catch (err)`` block renders the upstream-error
 * card. The ``ProfessionFilter`` Client Component is the
 * only client-side island on the page; it reads the same
 * ``searchParams.profession`` and provides the dropdown
 * UI for the user to change the value.
 */
export default async function PlayersPage(props: {
  searchParams: Promise<{ profession?: string }>;
}) {
  const searchParams = await props.searchParams;
  const professionFilter = searchParams.profession;
  let rows: Awaited<ReturnType<typeof fetchPlayers>> = [];
  let fetchError: string | null = null;
  try {
    rows = await fetchPlayers(
      professionFilter ? { profession: professionFilter } : {},
    );
  } catch (err) {
    fetchError = formatApiError(err);
  }

  return (
    <main
      style={{
        padding: "32px",
        display: "flex",
        flexDirection: "column",
        gap: "16px",
        width: "100%",
      }}
    >
      <header>
        <h1 style={{ fontSize: 28, marginBottom: 4 }}>Players</h1>
        {/* 2026-07-16 mobile+a11y audit P2: replace the
            fragile ``opacity: 0.7`` muted-text pattern with
            the theme-aware ``--foreground-muted`` token so
            the contrast is locked at ~4.6:1 (WCAG AA) and
            future theme changes can't drop it below 4.5:1. */}
        <p style={{ color: "var(--foreground-muted)" }}>
          {rows.length} player{rows.length === 1 ? "" : "s"} across the
          cross-fight roll-up. Use the search bar in the header to
          jump to a specific account.
        </p>
      </header>

      <ProfessionFilter currentValue={professionFilter} />

      {/* v0.10.0 plan 032: a small "Compare" CTA so the
          analyst can jump to the cross-account view from
          the players list. The query string is pre-loaded
          with the first 2 rows' account names so the
          landing page on /players/compare is non-empty;
          the analyst can edit the URL to add more
          accounts. The CTA is disabled when the list
          has fewer than 2 rows (the compare page requires
          at least 2 accounts). */}
      <CompareCta rows={rows} />

      {fetchError ? (
        <p style={{ color: "var(--accent)" }}>{fetchError}</p>
      ) : (
        <PlayersGrid rows={rows} filename="players.csv" />
      )}
    </main>
  );
}
