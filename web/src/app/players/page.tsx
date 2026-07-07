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

import { fetchPlayers, formatApiError } from "@/lib/api";
import { PlayersGrid } from "@/components/PlayersGrid";

export const dynamic = "force-dynamic";

export default async function PlayersPage() {
  let rows: Awaited<ReturnType<typeof fetchPlayers>> = [];
  let fetchError: string | null = null;
  try {
    rows = await fetchPlayers();
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
      }}
    >
      <header>
        <h1 style={{ fontSize: 28, marginBottom: 4 }}>Players</h1>
        <p style={{ opacity: 0.7 }}>
          {rows.length} player{rows.length === 1 ? "" : "s"} across the
          cross-fight roll-up. Use the search bar in the header to
          jump to a specific account.
        </p>
      </header>

      {fetchError ? (
        <p style={{ color: "var(--accent)" }}>{fetchError}</p>
      ) : (
        <PlayersGrid rows={rows} filename="players.csv" />
      )}
    </main>
  );
}
