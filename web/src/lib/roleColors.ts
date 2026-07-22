/** Shared role badge colors — single source of truth.
 *
 *  Used by {@link FightSummaryCards} and {@link ReadoutTabClient}
 *  so adding a new role only requires one edit.
 */
export interface RoleColor {
  bg: string;
  fg: string;
}

export const ROLE_COLORS: Record<string, RoleColor> = {
  DPS: { bg: "rgba(239,68,68,0.15)", fg: "#f87171" },
  Heal: { bg: "rgba(34,197,94,0.15)", fg: "#4ade80" },
  Support: { bg: "rgba(168,85,247,0.15)", fg: "#c084fc" },
  Strip: { bg: "rgba(251,191,36,0.15)", fg: "#fbbf24" },
  Cleanser: { bg: "rgba(6,182,212,0.15)", fg: "#22d3ee" },
  CC: { bg: "rgba(249,115,22,0.15)", fg: "#fb923c" },
};

export const ROLE_FALLBACK: RoleColor = {
  bg: "rgba(255,255,255,0.06)",
  fg: "var(--foreground)",
};
