"use client";

/**
 * Client Component for the Tour 4 v0.10.13 plan 044
 * ``?account=`` URL filter on ``/fights/[id]``.
 *
 * Why a Client Component
 * ======================
 * The filter mutates the URL (``/fights/[id]?account=TestAccount.1234``)
 * which requires the Next.js client-side router APIs
 * (``useRouter`` + ``useSearchParams``). The surrounding
 * ``/fights/[id]`` page is a Server Component; this filter is the
 * ONLY client-side island introduced by Tour 4 (consistent with
 * the precedent set by :component::``ProfessionFilter`` on
 * ``/players`` + :component::``TargetFilter`` on ``/fights/[id]``).
 *
 * Why a passed-in option list (not an API call)
 * =============================================
 * The page pre-loads ``OrmFightAgent`` rows via
 * :func::``fetchFight`` (the existing ``GET /api/v1/fights/{id}``
 * endpoint) and filters for ``is_player=true &&
 * account_name!=null``. Passing the filtered list as a prop
 * avoids a client-side round-trip + the render-flash of an
 * empty ``<select>`` on first load. The labels are formatted
 * upstream in the page (``name (account_name)`` truncated for
 * readability) -- this component is intentionally dumb about
 * label formatting.
 *
 * URL contract
 * ============
 * - Selecting an account sets ``?account=<NAME>`` and navigates
 *   to the new URL (``router.push``).
 * - Selecting "All players" removes the param.
 * - The pre-selected value comes from the parent's
 *   ``searchParams.account`` (the Server Component reads the
 *   URL + passes the value as a prop). This avoids a duplicate
 *   read from ``useSearchParams`` (the Server Component is the
 *   single source of truth for the URL state + the LRU
 *   ``fetchCached`` cache key).
 */
import { useRouter, useSearchParams } from "next/navigation";

interface PlayerAgentOption {
  /** Account name (the URL value, e.g. ``"TestAccount.1234"``). */
  account_name: string;
  /** Display label (e.g. ``"TestAccount.1234 (Warrior)"``). */
  label: string;
}

export function PlayerSkillUsageFilter({
  currentValue,
  playerAgents,
  fightId,
}: {
  /**
   * The current account filter from the URL
   * (``searchParams.account``). ``null`` or ``undefined``
   * when the URL has no filter (the "All players" option
   * is pre-selected in that case).
   */
  currentValue?: string | null;
  /**
   * The list of player agents available for selection.
   * Filtered upstream (``is_player === true`` +
   * ``account_name !== null``); the component renders
   * the list verbatim WITHOUT additional filtering so
   * callers control the option set.
   */
  playerAgents: PlayerAgentOption[];
  fightId: string;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();

  const handleChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const newValue = e.target.value;
    // ``new URLSearchParams(searchParams.toString())`` is a
    // defensive copy so we don't mutate the read-only
    // ``searchParams`` returned by Next.js. ``toString()``
    // materialises the current state into a mutable copy AND
    // preserves the existing query-string params (``window_s``,
    // ``target``, ``tab``) so the analyst's other filter
    // selections persist across the per-player toggle.
    const params = new URLSearchParams(searchParams.toString());
    if (newValue) {
      params.set("account", newValue);
    } else {
      params.delete("account");
    }
    const qs = params.toString();
    router.push(`/fights/${encodeURIComponent(fightId)}${qs ? `?${qs}` : ""}`);
  };

  if (playerAgents.length === 0) {
    // Empty-state return: the parent already renders a
    // "no players available" message when the fight is a
    // 0-player NPC-only fight; this component just returns
    // null so the page renders the existing placeholder.
    return null;
  }

  return (
    <label
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        fontSize: 14,
        opacity: 0.85,
      }}
    >
      Filter by player:
      <select
        data-testid="player-skill-filter"
        aria-label="Filter per-skill attribution by player"
        value={currentValue ?? ""}
        onChange={handleChange}
        style={{
          padding: "6px 10px",
          fontSize: 14,
          background: "var(--bg-elev)",
          color: "inherit",
          border: "1px solid var(--border)",
          borderRadius: 4,
        }}
      >
        <option value="">All players</option>
        {playerAgents.map((opt) => (
          <option key={opt.account_name} value={opt.account_name}>
            {opt.label}
          </option>
        ))}
      </select>
    </label>
  );
}
