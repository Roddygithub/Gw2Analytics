/**
 * Server Component that fetches the v0.7.0-api
 * ``GET /api/v1/players/{account_name:path}`` profile and
 * renders the cross-fight roll-up + per-fight breakdown.
 *
 * Why a Server Component
 * ======================
 * The data source is the gateway's per-account roll-up
 * (Postgres-backed for the per-fight agents table, with the
 * per-fight contribution computation in
 * :func:`apps.api.routes.players._compute_contributions`).
 * Server-side fetch avoids the client-side waterfall and
 * ensures the initial response is fully populated for the
 * URL-permalinkable ``account_name`` (so an analyst can
 * bookmark or share a specific player's profile).
 *
 * Force-dynamic
 * =============
 * ``export const dynamic = "force-dynamic"`` opts out of
 * Next.js's static caching so the profile reflects the latest
 * parsed fight state on every request.
 *
 * URL encoding
 * ============
 * ``account_name`` is URL-decoded by Next.js before being
 * handed to the handler; the fetcher URL-encodes the value
 * via ``encodeURIComponent`` before hitting the gateway so
 * the FastAPI ``:path`` converter receives a single path
 * segment. Account names commonly contain ``:`` (e.g.
 * ``:account.1234`` or ``:synth.abc123``) so the encoding
 * is the canonical guard.
 *
 * Empty + 404 + upstream-error handling
 * =====================================
 * - empty breakdown (``per_fight_breakdown == []``) -> the
 *   breakdown table renders a styled "no rows" panel. This
 *   is the canonical "account has no fight rows" case (the
 *   route still returns a profile with the cross-fight totals
 *   even when the breakdown is empty; an analyst can spot a
 *   parsing quirk via the fights_attended count).
 * - ``ApiError(404, ...)`` from the gateway -> the page
 *   renders an upstream-error card with the gateway's error
 *   body. The page does NOT raise 404 itself; the canonical
 *   404 lives at the API boundary, and the analyst surface
 *   just shows the upstream message.
 * - any other thrown error (network, 5xx) -> the same
 *   upstream-error card with the error message.
 */

import {
  ApiError,
  fetchPlayer,
  fetchPlayerTimeline,
  formatApiError,
} from "@/lib/api";
import { PlayerTimelineSection } from "@/components/PlayerTimelineSection";

export const dynamic = "force-dynamic";

const TABLE_STYLE: React.CSSProperties = {
  width: "100%",
  borderCollapse: "collapse",
  fontSize: 14,
  fontFamily: "var(--font-geist-mono), ui-monospace, monospace",
};

const TH_STYLE: React.CSSProperties = {
  textAlign: "left",
  padding: "8px 12px",
  borderBottom: "1px solid var(--border)",
  color: "var(--foreground)",
  opacity: 0.7,
  fontWeight: 600,
  fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
};

const TD_STYLE: React.CSSProperties = {
  padding: "6px 12px",
  borderBottom: "1px solid var(--border)",
  color: "var(--foreground)",
};

const EMPTY_STYLE: React.CSSProperties = {
  padding: "12px 16px",
  border: "1px solid var(--border)",
  borderRadius: 4,
  color: "var(--foreground)",
  opacity: 0.7,
  fontSize: 14,
  fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
};

export default async function PlayerProfilePage({
  params,
}: {
  params: Promise<{ account_name: string }>;
}) {
  const { account_name } = await params;

  let profile: Awaited<ReturnType<typeof fetchPlayer>> | null = null;
  let fetchError: string | null = null;
  // v0.8.0 of web: also fetch the per-account historical
  // timeline (the first page only) on the server. A 404
  // from the timeline endpoint is the canonical "player has
  // no attended fights" case; we swallow it and render the
  // chart with the empty-state panel instead of bailing
  // out of the whole page (the profile is still useful for
  // a player with zero attended fights once the dataset
  // is later populated). Any other error is treated as a
  // fatal upstream error and renders the same error card
  // the profile fetch uses.
  let timeline:
    | Awaited<ReturnType<typeof fetchPlayerTimeline>>
    | null = null;
  let timelineError: string | null = null;
  try {
    profile = await fetchPlayer(account_name);
  } catch (err) {
    fetchError = formatApiError(err);
  }
  if (profile) {
    try {
      timeline = await fetchPlayerTimeline(account_name, { limit: 20 });
    } catch (err) {
      // 404 (player not in any fight) is the only "expected"
      // failure mode; the chart's empty-state panel handles
      // a null timeline. Any other error is fatal to the
      // page (matches the profile-fetch contract). Using
      // ``ApiError`` + ``err.status`` is the canonical
      // discriminator (a string-based ``startsWith("404:")``
      // would couple to the ApiError's formatted message).
      if (err instanceof ApiError && err.status === 404) {
        timeline = null;
      } else {
        timelineError = formatApiError(err);
      }
    }
  }

  // v0.8.0 of web: always render the section so the
  // analyst sees a "Showing 0 of 0 fights" caption + the
  // chart's empty-state panel + a disabled "All fights
  // loaded" button when the player has no attended fights.
  // Silently omitting the section on a 404 would be
  // ambiguous (the analyst would not know whether the
  // section was broken or whether the player simply has no
  // history). The section is only suppressed on a fatal
  // timeline error (handled by the upstream-error card
  // above).
  const effectiveTimeline =
    timeline ?? {
      account_name: account_name,
      total: 0,
      limit: 20,
      offset: 0,
      // v0.8.1 of web: the empty-state timeline carries
      // ``bucket: "fight"`` to match the default the route
      // returns. The toggle in :class:`PlayerTimelineSection`
      // reads ``initialTimeline.bucket`` to initialise its
      // own state, so a missing field would trip TypeScript
      // and (worse) make the section's "Per day" button
      // appear already-active on a freshly-loaded empty
      // timeline.
      bucket: "fight",
      // v0.8.9 of web: mirror the v0.8.9 API default
      // (``tz: "UTC"``) on the empty-state fallback. The
      // section reads ``initialTimeline.tz`` to thread
      // through to the timeline fetch, so a missing field
      // would trip TypeScript strict-mode.
      tz: "UTC",
      points: [],
    };

  if (fetchError || timelineError || !profile) {
    return (
      <main style={{ padding: "32px", width: "100%" }}>
        <header style={{ marginBottom: 16 }}>
          <h1 style={{ fontSize: 28, marginBottom: 4 }}>
            Player {account_name}
          </h1>
          <p style={{ opacity: 0.7 }}>
            Cross-fight profile + per-fight breakdown.
          </p>
        </header>
        <p style={{ color: "var(--accent)" }}>
          {fetchError ?? timelineError}
        </p>
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
        // v0.10.0 plan 032: explicit ``width: 100%`` on the
        // main element so the page fills the 1440x900
        // visual-regression viewport even when a downstream
        // CSS rule (e.g. a child element with a fixed
        // ``max-width`` or a wide horizontal scroll) would
        // otherwise shrink the parent's intrinsic width.
        // The bug was a 900px-wide render on the seeded
        // ``:demo.<N>`` accounts (per the visual-regression
        // suite) -- the page rendered the chart + table
        // but the page-level ``<main>`` collapsed to
        // ~900px instead of filling the viewport. This
        // explicit width is the defensive fix: it does not
        // change the layout when the page renders
        // correctly (a block element already fills the
        // viewport by default) and it prevents the silent
        // collapse when a child element is wider than its
        // content.
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
        <h1 style={{ fontSize: 28, marginBottom: 4 }}>{profile.name}</h1>
        <p style={{ opacity: 0.7, fontFamily: "var(--font-geist-mono), ui-monospace, monospace" }}>
          {profile.account_name} · {profile.profession} · {profile.elite_spec}
        </p>
      </header>

      <section
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
          gap: 16,
        }}
      >
        <Stat label="Fights attended" value={String(profile.fights_attended)} />
        <Stat label="Total damage" value={String(profile.total_damage)} />
        <Stat label="Total healing" value={String(profile.total_healing)} />
        <Stat
          label="Total buff removal"
          value={String(profile.total_buff_removal)}
        />
      </section>

      <PlayerTimelineSection
        accountName={account_name}
        initialTimeline={effectiveTimeline}
      />

      <section style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <h2 style={{ fontSize: 18, fontWeight: 600 }}>Per-fight breakdown</h2>
        {profile.per_fight_breakdown.length === 0 ? (
          <div style={EMPTY_STYLE}>No attended fights.</div>
        ) : (
          <table style={TABLE_STYLE}>
            <thead>
              <tr>
                <th style={TH_STYLE}>Fight</th>
                <th style={TH_STYLE}>Started at</th>
                <th style={{ ...TH_STYLE, textAlign: "right" }}>Damage</th>
                <th style={{ ...TH_STYLE, textAlign: "right" }}>Healing</th>
                <th style={{ ...TH_STYLE, textAlign: "right" }}>Strip</th>
              </tr>
            </thead>
            <tbody>
              {profile.per_fight_breakdown.map((row) => (
                <tr key={row.fight_id}>
                  <td style={TD_STYLE}>
                    <a
                      href={`/fights/${encodeURIComponent(row.fight_id)}`}
                      style={{ color: "var(--accent)" }}
                    >
                      {row.fight_id}
                    </a>
                  </td>
                  <td style={TD_STYLE}>{row.started_at}</td>
                  <td style={{ ...TD_STYLE, textAlign: "right" }}>
                    {row.total_damage}
                  </td>
                  <td style={{ ...TD_STYLE, textAlign: "right", color: "var(--accent)" }}>
                    {row.total_healing}
                  </td>
                  <td style={{ ...TD_STYLE, textAlign: "right" }}>
                    {row.total_buff_removal}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </main>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div
      style={{
        padding: "12px 16px",
        border: "1px solid var(--border)",
        borderRadius: 4,
        background: "var(--surface)",
      }}
    >
      <div
        style={{
          fontSize: 11,
          opacity: 0.7,
          textTransform: "uppercase",
          letterSpacing: "0.06em",
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: 20,
          fontWeight: 600,
          marginTop: 4,
          fontFamily: "var(--font-geist-mono), ui-monospace, monospace",
        }}
      >
        {value}
      </div>
    </div>
  );
}
