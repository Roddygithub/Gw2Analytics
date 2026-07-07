/**
 * Server Component that fetches /api/v1/fights from the FastAPI
 * gateway and renders the AG Grid table on the client.
 *
 * Why Server Component
 * ====================
 * The data source is the gateway's Postgres-backed list endpoint;
 * fetching on the server avoids a client-side waterfall (the
 * browser hits /fights -> gateway -> Postgres) and ensures the
 * initial response is fully populated for SEO and accessibility.
 *
 * Force-dynamic
 * =============
 * ``export const dynamic = "force-dynamic"`` opts out of Next.js's
 * static caching so the table reflects the latest parsed fights on
 * every request. The endpoint is paginated server-side so we don't
 * page through Postgres here.
 */

import { fetchFights } from "@/lib/api";
import { FightsGrid } from "@/components/FightsGrid";

export const dynamic = "force-dynamic";

export default async function FightsPage() {
  let rows: Awaited<ReturnType<typeof fetchFights>> = [];
  let fetchError: string | null = null;
  try {
    rows = await fetchFights();
  } catch (err) {
    fetchError = err instanceof Error ? err.message : String(err);
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
        <h1 style={{ fontSize: 28, marginBottom: 4 }}>Fights</h1>
        <p style={{ opacity: 0.7 }}>
          {rows.length} fight{rows.length === 1 ? "" : "s"} parsed and
          persisted.
        </p>
      </header>

      {fetchError ? (
        <p style={{ color: "var(--accent)" }}>
          Upstream error: {fetchError}
        </p>
      ) : (
        <FightsGrid rows={rows} />
      )}
    </main>
  );
}
