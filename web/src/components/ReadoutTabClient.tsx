"use client";

/**
 * Client-side tab that fetches the combat readout + positions + events
 * and renders the full fight analysis view with native HTML tables:
 *   - Summary cards (Top 3 per category)
 *   - Timeline chart
 *   - 4 native HTML tables (Damage, Heal, Boons, Defense)
 */

import React, { useCallback, useEffect, useMemo, useState } from "react";

import {
  fetchFightReadout,
  fetchFightPositions,
  fetchFightEvents,
  type FightReadoutOut,
  type FightPositionsOut,
  type FightEventsSummaryRow,
  type PlayerReadoutOut,
} from "@/lib/api";
import { FightSummaryCards } from "./FightSummaryCards";
import {
  EliteSpecCellRenderer,
  CommanderCellRenderer,
} from "./PlayerReadoutCells";
import { ROLE_COLORS, ROLE_FALLBACK } from "@/lib/roleColors";

/* ------------------------------------------------------------------ *
 *  Constants & shared styles
 * ------------------------------------------------------------------ */

type SortField = string;
type SortDir = "asc" | "desc";

const TABLE_STYLE: React.CSSProperties = {
  width: "100%",
  borderCollapse: "collapse",
  fontSize: 12,
  fontFamily: "var(--font-geist-sans, sans-serif)",
  background: "var(--surface, rgba(255,255,255,0.02))",
  borderRadius: 6,
  overflow: "hidden",
};

const TH_STYLE: React.CSSProperties = {
  position: "sticky",
  top: 0,
  padding: "6px 8px",
  textAlign: "left",
  fontWeight: 600,
  fontSize: 10,
  textTransform: "uppercase",
  letterSpacing: "0.05em",
  color: "var(--foreground)",
  opacity: 0.7,
  background: "var(--surface-elevated, rgba(255,255,255,0.05))",
  borderBottom: "1px solid var(--border)",
  whiteSpace: "nowrap",
  cursor: "pointer",
  userSelect: "none",
};

const TD_STYLE: React.CSSProperties = {
  padding: "4px 8px",
  borderBottom: "1px solid var(--border)",
  color: "var(--foreground)",
  whiteSpace: "nowrap",
};

const EMPTY_STYLE: React.CSSProperties = {
  padding: "12px 16px",
  border: "1px solid var(--border)",
  borderRadius: 4,
  color: "var(--foreground)",
  opacity: 0.7,
};

const BAR_BG = "rgba(255,255,255,0.05)";
const BAR_HEIGHT = 14;

/* ------------------------------------------------------------------ *
 *  Bar chart helpers
 * ------------------------------------------------------------------ */

function MiniBar({ pct, color }: { pct: number; color: string }) {
  return (
    <div
      style={{
        width: `${Math.max(pct, 1)}%`,
        height: "100%",
        background: color,
        borderRadius: 2,
        transition: "width 0.3s",
        minWidth: 4,
      }}
    />
  );
}

function DpsBar({ power, condi, total }: { power: number; condi: number; total: number }) {
  const max = Math.max(total, 1);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <div style={{ flex: 1, height: BAR_HEIGHT, background: BAR_BG, borderRadius: 3, overflow: "hidden", display: "flex", minWidth: 60 }}>
        <MiniBar pct={(power / max) * 100} color="linear-gradient(90deg, #f59e0b, #d97706)" />
        <MiniBar pct={(condi / max) * 100} color="linear-gradient(90deg, #ef4444, #dc2626)" />
      </div>
      <span style={{ fontWeight: 700, fontVariantNumeric: "tabular-nums", minWidth: 48, textAlign: "right" }}>
        {total.toFixed(0)}
      </span>
    </div>
  );
}

function HealBar({ hps, bps, total }: { hps: number; bps: number; total: number }) {
  const max = Math.max(hps + bps, 1);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <div style={{ flex: 1, height: BAR_HEIGHT, background: BAR_BG, borderRadius: 3, overflow: "hidden", display: "flex", minWidth: 60 }}>
        <MiniBar pct={(hps / max) * 100} color="linear-gradient(90deg, #22c55e, #16a34a)" />
        <MiniBar pct={(bps / max) * 100} color="linear-gradient(90deg, #06b6d4, #0891b2)" />
      </div>
      <span style={{ fontWeight: 700, fontVariantNumeric: "tabular-nums", minWidth: 48, textAlign: "right" }}>
        {total.toFixed(0)}
      </span>
    </div>
  );
}

/* ------------------------------------------------------------------ *
 *  Role badge
 * ------------------------------------------------------------------ */

function RoleBadge({ role }: { role: string }) {
  const c = ROLE_COLORS[role] ?? ROLE_FALLBACK;
  return (
    <span
      style={{
        padding: "0 5px",
        borderRadius: 3,
        fontSize: 9,
        fontWeight: 700,
        lineHeight: "15px",
        background: c.bg,
        color: c.fg,
        letterSpacing: "0.03em",
      }}
    >
      {role}
    </span>
  );
}

/* ------------------------------------------------------------------ *
 *  Sortable table header
 * ------------------------------------------------------------------ */

function Th({
  children,
  field,
  currentSort,
  onSort,
  style,
  colSpan,
  rowSpan,
}: {
  children: React.ReactNode;
  field: string;
  currentSort: { field: SortField; dir: SortDir } | null;
  onSort: (field: SortField) => void;
  style?: React.CSSProperties;
  colSpan?: number;
  rowSpan?: number;
}) {
  const active = currentSort?.field === field;
  return (
    <th
      style={{ ...TH_STYLE, ...style }}
      colSpan={colSpan}
      rowSpan={rowSpan}
      onClick={() => onSort(field)}
    >
      {children}
      {active && (
        <span style={{ marginLeft: 2, fontSize: 9 }}>
          {currentSort?.dir === "asc" ? " ▲" : " ▼"}
        </span>
      )}
    </th>
  );
}

/* ------------------------------------------------------------------ *
 *  Shared identity cells (Groupe, Nom, Spé, Cmd, Rôles)
 * ------------------------------------------------------------------ */

function IdentityCells({ player }: { player: PlayerReadoutOut }) {
  return (
    <>
      <td style={TD_STYLE}>
        {player.subgroup === 0 ? "—" : `Sub ${player.subgroup}`}
      </td>
      <td style={{ ...TD_STYLE, fontWeight: 500 }}>{player.name}</td>
      <td style={TD_STYLE}>
        <EliteSpecCellRenderer data={player} />
      </td>
      <td style={{ ...TD_STYLE, textAlign: "center" }}>
        <CommanderCellRenderer data={player} />
      </td>
      <td style={TD_STYLE}>
        <span style={{ display: "inline-flex", gap: 2, flexWrap: "wrap" }}>
          {player.roles.map((r) => (
            <RoleBadge key={r} role={r} />
          ))}
        </span>
      </td>
    </>
  );
}

/* ------------------------------------------------------------------ *
 *  Boon definitions
 * ------------------------------------------------------------------ */

interface BoonDef {
  key: string;
  label: string;
}

const BOONS: BoonDef[] = [
  { key: "might", label: "Might" },
  { key: "fury", label: "Fury" },
  { key: "quickness", label: "Quick" },
  { key: "alacrity", label: "Alac" },
  { key: "protection", label: "Prot" },
  { key: "regeneration", label: "Regen" },
  { key: "vigor", label: "Vigor" },
  { key: "aegis", label: "Aegis" },
  { key: "stability", label: "Stab" },
  { key: "swiftness", label: "Swift" },
  { key: "resistance", label: "Resist" },
  { key: "resolution", label: "Resol" },
  { key: "superspeed", label: "Speed" },
  { key: "stealth", label: "Stealth" },
];

/* ------------------------------------------------------------------ *
 *  Sorting hook
 * ------------------------------------------------------------------ */

function useSortedPlayers(
  players: PlayerReadoutOut[],
  defaultField: SortField,
  defaultDir: SortDir,
) {
  const [sort, setSort] = useState<{ field: SortField; dir: SortDir }>({
    field: defaultField,
    dir: defaultDir,
  });

  const onSort = useCallback(
    (field: SortField) => {
      setSort((prev) => ({
        field,
        dir: prev.field === field && prev.dir === "desc" ? "asc" : "desc",
      }));
    },
    [],
  );

  const sorted = useMemo(() => {
    const dir = sort.dir === "asc" ? 1 : -1;
    return [...players].sort((a, b) => {
      const va = getSortValue(a, sort.field);
      const vb = getSortValue(b, sort.field);
      if (va === vb) return 0;
      return va < vb ? -dir : dir;
    });
  }, [players, sort]);

  return { sorted, sort, onSort };
}

function getSortValue(p: PlayerReadoutOut, field: string): number {
  if (field === "dps_total") return p.damage.dps_total;
  if (field === "dps_power") return p.damage.dps_power;
  if (field === "dps_condi") return p.damage.dps_condi;
  if (field === "strips") return p.damage.strips;
  if (field === "cc_applied") return p.damage.cc_applied;
  if (field === "down_contrib") return p.damage.down_contribution_dps;
  if (field === "cleave") return p.damage.cleave_targets;
  if (field === "kills") return p.damage.kills;
  if (field === "kill_part") return p.damage.kill_participation;
  if (field === "heal_total") return p.heal.heal_total ?? 0;
  if (field === "hps") return p.heal.hps;
  if (field === "barrier_ps") return p.heal.barrier_ps;
  if (field === "cleanses") return p.heal.cleanses;
  if (field === "stun_breaks") return p.heal.stun_breaks;
  if (field === "damage_taken") return p.defense.damage_taken;
  if (field === "deaths") return p.defense.deaths;
  if (field === "dodges") return p.defense.dodges;
  if (field === "blocks") return p.defense.blocks;
  if (field === "interrupts") return p.defense.interrupts;
  if (field === "cc_taken") return p.defense.cc_taken;
  if (field === "time_downed") return p.defense.time_downed_ms;
  if (field === "barrier_absorbed") return p.defense.barrier_absorbed;
  if (field === "presence_pct") return p.defense.presence_pct ?? 0;
  if (field === "subgroup") return p.subgroup;
  if (field.startsWith("boon_in_")) {
    const boonKey = field.replace("boon_in_", "");
    return (p.boons as unknown as Record<string, number | null>)[`${boonKey}_uptime`] ?? -1;
  }
  if (field.startsWith("boon_out_")) {
    const boonKey = field.replace("boon_out_", "");
    return (p.boons as unknown as Record<string, number | null>)[`outgoing_${boonKey}`] ?? -1;
  }
  if (field === "name") return (p.name || "").charCodeAt(0) || 0;
  return 0;
}

/* ------------------------------------------------------------------ *
 *  Timeline mini chart
 * ------------------------------------------------------------------ */

function TimelineMiniChart({ events }: { events: FightEventsSummaryRow | null }) {
  if (!events || events.event_windows.length === 0) {
    return (
      <div style={EMPTY_STYLE}>
        Aucune donnée temporelle disponible.
      </div>
    );
  }

  const raw = events.event_windows;
  const MAX_BARS = 200;

  // Downsample: if >MAX_BARS windows, merge adjacent windows into groups.
  const windows = useMemo(() => {
    if (raw.length <= MAX_BARS) return raw;
    const groupSize = Math.ceil(raw.length / MAX_BARS);
    const result: typeof raw = [];
    for (let i = 0; i < raw.length; i += groupSize) {
      const slice = raw.slice(i, i + groupSize);
      result.push({
        start_ms: slice[0].start_ms,
        end_ms: slice[slice.length - 1].end_ms,
        damage_total: slice.reduce((s, w) => s + w.damage_total, 0),
        healing_total: slice.reduce((s, w) => s + w.healing_total, 0),
        event_count: slice.reduce((s, w) => s + w.event_count, 0),
      });
    }
    return result;
  }, [raw]);

  const maxDmg = Math.max(...windows.map((w) => w.damage_total), 1);
  const maxHeal = Math.max(...windows.map((w) => w.healing_total), 1);
  const durationMin = (raw[raw.length - 1]?.end_ms ?? 0) / 60000;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, fontSize: 12 }}>
        <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ width: 10, height: 10, borderRadius: 2, background: "#f59e0b" }} />
          Damage
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ width: 10, height: 10, borderRadius: 2, background: "#22c55e" }} />
          Heal
        </span>
        <span style={{ marginLeft: "auto", opacity: 0.6 }}>
          {raw.length} buckets · {durationMin.toFixed(1)} min
          {windows.length < raw.length && ` (affiché: ${windows.length})`}
        </span>
      </div>
      <div
        style={{
          width: "100%",
          height: 80,
          display: "flex",
          alignItems: "flex-end",
          gap: 1,
          background: "rgba(255,255,255,0.03)",
          borderRadius: 4,
          padding: "4px 0",
          overflow: "hidden",
        }}
      >
        {windows.map((w, i) => {
          const dmgPct = (w.damage_total / maxDmg) * 100;
          const healPct = (w.healing_total / maxHeal) * 100;
          return (
            <div
              key={i}
              style={{
                flex: 1,
                height: "100%",
                display: "flex",
                flexDirection: "column-reverse",
                alignItems: "center",
                gap: 1,
                minWidth: 2,
              }}
              title={`${(w.start_ms / 1000).toFixed(0)}s: dmg=${w.damage_total}, heal=${w.healing_total}`}
            >
              <div
                style={{
                  width: "100%",
                  height: `${Math.max(healPct, 1)}%`,
                  background: "#22c55e",
                  opacity: 0.6,
                  borderRadius: "1px 1px 0 0",
                }}
              />
              <div
                style={{
                  width: "100%",
                  height: `${Math.max(dmgPct, 1)}%`,
                  background: "#f59e0b",
                  opacity: 0.8,
                  borderRadius: "1px 1px 0 0",
                }}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ *
 *  Positions summary
 * ------------------------------------------------------------------ */

function PositionsSummary({ positions }: { positions: FightPositionsOut | null }) {
  if (!positions || positions.players.length === 0) {
    return <div style={EMPTY_STYLE}>Aucune donnée de position.</div>;
  }

  const closePlayers = [...positions.players]
    .sort((a, b) => (a.stack_dist ?? 9999) - (b.stack_dist ?? 9999))
    .slice(0, 5);

  return (
    <div style={{ fontSize: 13, display: "flex", flexDirection: "column", gap: 8 }}>
      <p style={{ opacity: 0.7, margin: 0 }}>
        {positions.players.length} joueurs trackés ·{" "}
        {closePlayers[0]?.stack_dist
          ? `Plus proche stack: ${closePlayers[0].name} (${closePlayers[0].stack_dist?.toFixed(1)}u)`
          : ""}
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ *
 *  Wrapper for scrollable tables
 * ------------------------------------------------------------------ */

function TableWrapper({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        width: "100%",
        overflowX: "auto",
        border: "1px solid var(--border)",
        borderRadius: 6,
        maxHeight: 600,
        overflowY: "auto",
      }}
    >
      {children}
    </div>
  );
}

/* ------------------------------------------------------------------ *
 *  ReadoutTabClient — main component
 * ------------------------------------------------------------------ */

interface ReadoutTabClientProps {
  fightId: string;
}

export function ReadoutTabClient({ fightId }: ReadoutTabClientProps) {
  const [readout, setReadout] = useState<FightReadoutOut | null>(null);
  const [positions, setPositions] = useState<FightPositionsOut | null>(null);
  const [events, setEvents] = useState<FightEventsSummaryRow | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [r, p, e] = await Promise.all([
        fetchFightReadout(fightId),
        fetchFightPositions(fightId).catch(() => null),
        fetchFightEvents(fightId).catch(() => null),
      ]);
      setReadout(r);
      setPositions(p);
      setEvents(e);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load combat data");
    } finally {
      setLoading(false);
    }
  }, [fightId]);

  useEffect(() => { load(); }, [load]);

  // Role filter — MUST be before early returns
  const players = readout?.players ?? [];
  const [roleFilter, setRoleFilter] = useState<string | null>(null);
  const allRoles = useMemo(() => {
    const seen = new Set<string>();
    for (const p of players) for (const r of p.roles) seen.add(r);
    return [...seen].sort();
  }, [players]);
  const filteredPlayers = useMemo(() => {
    if (!roleFilter) return players;
    return players.filter((p) => p.roles.includes(roleFilter));
  }, [players, roleFilter]);

  // Sort states
  const damageSort = useSortedPlayers(filteredPlayers, "dps_total", "desc");
  const healSort = useSortedPlayers(filteredPlayers, "hps", "desc");
  const boonSort = useSortedPlayers(filteredPlayers, "boon_in_might", "desc");
  const defenseSort = useSortedPlayers(filteredPlayers, "damage_taken", "desc");

  if (loading) {
    return (
      <div style={{ padding: "24px 0", display: "flex", alignItems: "center", gap: 12, opacity: 0.7 }}>
        <span aria-label="Chargement">⏳</span> Chargement des données de combat…
      </div>
    );
  }

  if (error || !readout) {
    return (
      <div style={{ padding: "16px 20px", border: "1px solid var(--accent)", borderRadius: 4, color: "var(--accent)" }} role="alert">
        {error ?? "Impossible de charger les données de combat."}
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      {/* Role filter */}
      {allRoles.length > 1 && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <label style={{ fontSize: 12, opacity: 0.7 }}>Filtrer par rôle :</label>
          <select
            value={roleFilter ?? ""}
            onChange={(e) => setRoleFilter(e.target.value || null)}
            style={{
              padding: "3px 8px", borderRadius: 4, border: "1px solid var(--border)",
              background: "var(--surface)", color: "var(--foreground)", fontSize: 12,
              fontFamily: "var(--font-geist-sans, sans-serif)",
            }}
          >
            <option value="">Tous ({players.length})</option>
            {allRoles.map((r) => (
              <option key={r} value={r}>{r} ({players.filter((p) => p.roles.includes(r)).length})</option>
            ))}
          </select>
          {roleFilter && (
            <>
              <span style={{
                fontSize: 11, opacity: 0.6, fontVariantNumeric: "tabular-nums",
                padding: "1px 8px", borderRadius: 3, background: "var(--surface)", border: "1px solid var(--border)",
              }}>
                {filteredPlayers.length}&nbsp;/&nbsp;{players.length} joueurs
              </span>
              <button
                onClick={() => setRoleFilter(null)}
                style={{
                  padding: "0 6px", borderRadius: 3, border: "1px solid var(--border)",
                  background: "var(--surface)", color: "var(--foreground)", cursor: "pointer",
                  fontSize: 11, lineHeight: "18px", fontFamily: "var(--font-geist-sans, sans-serif)", opacity: 0.7,
                }}
                title="Réinitialiser le filtre"
              >
                ✕
              </button>
            </>
          )}
        </div>
      )}

      <p style={{ padding: "10px 14px", border: "1px solid var(--border)", borderRadius: 4, fontSize: 13, opacity: 0.8 }}>
        {players.length} joueurs · durée {readout.duration_s.toFixed(1)}s
      </p>

      <FightSummaryCards players={players} onRoleFilter={setRoleFilter} />

      <section>
        <h2 style={{ fontSize: 18, fontWeight: 600, margin: "0 0 8px 0" }}>Timeline des événements</h2>
        <TimelineMiniChart events={events} />
      </section>

      {positions && (
        <section>
          <h2 style={{ fontSize: 18, fontWeight: 600, margin: "0 0 8px 0" }}>Positions</h2>
          <PositionsSummary positions={positions} />
        </section>
      )}

      {/* Tableau 1: Dégâts */}
      <section>
        <h2 style={{ fontSize: 18, fontWeight: 600, margin: "0 0 8px 0" }}>Dégâts</h2>
        <TableWrapper>
          <table style={TABLE_STYLE}>
            <thead>
              <tr>
                <Th field="subgroup" currentSort={damageSort.sort} onSort={damageSort.onSort}>Groupe</Th>
                <Th field="name" currentSort={damageSort.sort} onSort={damageSort.onSort}>Nom</Th>
                <Th field="" currentSort={null} onSort={() => {}} style={{ cursor: "default" }}>Spé</Th>
                <Th field="" currentSort={null} onSort={() => {}} style={{ cursor: "default", width: 40 }}>Cmd</Th>
                <Th field="" currentSort={null} onSort={() => {}} style={{ cursor: "default" }}>Rôles</Th>
                <Th field="dps_total" currentSort={damageSort.sort} onSort={damageSort.onSort} style={{ minWidth: 180 }}>DPS (power / condi)</Th>
                <Th field="strips" currentSort={damageSort.sort} onSort={damageSort.onSort}>Strips</Th>
                <Th field="cc_applied" currentSort={damageSort.sort} onSort={damageSort.onSort}>CC</Th>
                <Th field="down_contrib" currentSort={damageSort.sort} onSort={damageSort.onSort}>Down DPS</Th>
                <Th field="cleave" currentSort={damageSort.sort} onSort={damageSort.onSort}>Cleave</Th>
                <Th field="kills" currentSort={damageSort.sort} onSort={damageSort.onSort}>Kills</Th>
                <Th field="deaths" currentSort={damageSort.sort} onSort={damageSort.onSort}>Morts</Th>
                <Th field="kill_part" currentSort={damageSort.sort} onSort={damageSort.onSort}>Kill Part</Th>
              </tr>
            </thead>
            <tbody>
              {damageSort.sorted.map((p, i) => (
                <tr key={p.agent_id} style={{ background: i % 2 === 0 ? "transparent" : "rgba(255,255,255,0.015)" }}>
                  <IdentityCells player={p} />
                  <td style={TD_STYLE}><DpsBar power={p.damage.dps_power} condi={p.damage.dps_condi} total={p.damage.dps_total} /></td>
                  <td style={TD_STYLE}>{p.damage.strips}</td>
                  <td style={TD_STYLE}>{p.damage.cc_applied}</td>
                  <td style={TD_STYLE}>{p.damage.down_contribution_dps.toFixed(1)}</td>
                  <td style={TD_STYLE}>{p.damage.cleave_targets}</td>
                  <td style={TD_STYLE}>{p.damage.kills}</td>
                  <td style={TD_STYLE}>{p.defense.deaths}</td>
                  <td style={TD_STYLE}>{p.damage.kill_participation}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrapper>
      </section>

      {/* Tableau 2: Soins */}
      <section>
        <h2 style={{ fontSize: 18, fontWeight: 600, margin: "0 0 8px 0" }}>Soins</h2>
        <TableWrapper>
          <table style={TABLE_STYLE}>
            <thead>
              <tr>
                <Th field="subgroup" currentSort={healSort.sort} onSort={healSort.onSort}>Groupe</Th>
                <Th field="name" currentSort={healSort.sort} onSort={healSort.onSort}>Nom</Th>
                <Th field="" currentSort={null} onSort={() => {}} style={{ cursor: "default" }}>Spé</Th>
                <Th field="" currentSort={null} onSort={() => {}} style={{ cursor: "default", width: 40 }}>Cmd</Th>
                <Th field="" currentSort={null} onSort={() => {}} style={{ cursor: "default" }}>Rôles</Th>
                <Th field="hps" currentSort={healSort.sort} onSort={healSort.onSort} style={{ minWidth: 180 }}>Heal / Barrier</Th>
                <Th field="cleanses" currentSort={healSort.sort} onSort={healSort.onSort}>Cleanses</Th>
                <Th field="stun_breaks" currentSort={healSort.sort} onSort={healSort.onSort}>Breakstun</Th>
              </tr>
            </thead>
            <tbody>
              {healSort.sorted.map((p, i) => (
                <tr key={p.agent_id} style={{ background: i % 2 === 0 ? "transparent" : "rgba(255,255,255,0.015)" }}>
                  <IdentityCells player={p} />
                  <td style={TD_STYLE}><HealBar hps={p.heal.hps} bps={p.heal.barrier_ps} total={p.heal.heal_total ?? 0} /></td>
                  <td style={TD_STYLE}>{p.heal.cleanses}</td>
                  <td style={TD_STYLE}>{p.heal.stun_breaks}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrapper>
      </section>

      {/* Tableau 3: Boons — one column per boon with In (uptime%) / Out (total) */}
      <section>
        <h2 style={{ fontSize: 18, fontWeight: 600, margin: "0 0 8px 0" }}>Boons</h2>
        <TableWrapper>
          <table style={TABLE_STYLE}>
            <thead>
              <tr>
                <Th field="subgroup" currentSort={boonSort.sort} onSort={boonSort.onSort} rowSpan={2}>Groupe</Th>
                <Th field="name" currentSort={boonSort.sort} onSort={boonSort.onSort} rowSpan={2}>Nom</Th>
                <Th field="" currentSort={null} onSort={() => {}} style={{ cursor: "default" }} rowSpan={2}>Spé</Th>
                <Th field="" currentSort={null} onSort={() => {}} style={{ cursor: "default", width: 40 }} rowSpan={2}>Cmd</Th>
                <Th field="" currentSort={null} onSort={() => {}} style={{ cursor: "default" }} rowSpan={2}>Rôles</Th>
                {BOONS.map((b) => (
                  <th key={b.key} style={{ ...TH_STYLE, textAlign: "center", cursor: "default" }} colSpan={2}>
                    {b.label}
                  </th>
                ))}
              </tr>
              <tr>
                {BOONS.map((b) => (
                  <React.Fragment key={b.key}>
                    <Th field={`boon_in_${b.key}`} currentSort={boonSort.sort} onSort={boonSort.onSort} style={{ width: 42, textAlign: "center" }}>
                      In
                    </Th>
                    <Th field={`boon_out_${b.key}`} currentSort={boonSort.sort} onSort={boonSort.onSort} style={{ width: 42, textAlign: "center" }}>
                      Out
                    </Th>
                  </React.Fragment>
                ))}
              </tr>
            </thead>
            <tbody>
              {boonSort.sorted.map((p, i) => (
                <tr key={p.agent_id} style={{ background: i % 2 === 0 ? "transparent" : "rgba(255,255,255,0.015)" }}>
                  <IdentityCells player={p} />
                  {BOONS.map((b) => {
                    const boons = p.boons as unknown as Record<string, number | null>;
                    return (
                      <React.Fragment key={b.key}>
                        <td style={{ ...TD_STYLE, textAlign: "center", fontVariantNumeric: "tabular-nums" }}>
                          {boons[`${b.key}_uptime`] != null ? `${boons[`${b.key}_uptime`]!.toFixed(0)}%` : "—"}
                        </td>
                        <td style={{ ...TD_STYLE, textAlign: "center", fontVariantNumeric: "tabular-nums" }}>
                          {boons[`outgoing_${b.key}`] != null ? boons[`outgoing_${b.key}`]!.toLocaleString() : "—"}
                        </td>
                      </React.Fragment>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrapper>
      </section>

      {/* Tableau 4: Défense */}
      <section>
        <h2 style={{ fontSize: 18, fontWeight: 600, margin: "0 0 8px 0" }}>Défense &amp; Positionnement</h2>
        <TableWrapper>
          <table style={TABLE_STYLE}>
            <thead>
              <tr>
                <Th field="subgroup" currentSort={defenseSort.sort} onSort={defenseSort.onSort}>Groupe</Th>
                <Th field="name" currentSort={defenseSort.sort} onSort={defenseSort.onSort}>Nom</Th>
                <Th field="" currentSort={null} onSort={() => {}} style={{ cursor: "default" }}>Spé</Th>
                <Th field="" currentSort={null} onSort={() => {}} style={{ cursor: "default", width: 40 }}>Cmd</Th>
                <Th field="" currentSort={null} onSort={() => {}} style={{ cursor: "default" }}>Rôles</Th>
                <Th field="damage_taken" currentSort={defenseSort.sort} onSort={defenseSort.onSort}>Dmg reçu</Th>
                <Th field="dodges" currentSort={defenseSort.sort} onSort={defenseSort.onSort}>Esquives</Th>
                <Th field="blocks" currentSort={defenseSort.sort} onSort={defenseSort.onSort}>Blocages</Th>
                <Th field="interrupts" currentSort={defenseSort.sort} onSort={defenseSort.onSort}>Interrupt</Th>
                <Th field="deaths" currentSort={defenseSort.sort} onSort={defenseSort.onSort}>Morts</Th>
                <Th field="time_downed" currentSort={defenseSort.sort} onSort={defenseSort.onSort}>Down (ms)</Th>
                <Th field="cc_taken" currentSort={defenseSort.sort} onSort={defenseSort.onSort}>CC reçus</Th>
                <Th field="barrier_absorbed" currentSort={defenseSort.sort} onSort={defenseSort.onSort}>Barrier abs.</Th>
                <Th field="presence_pct" currentSort={defenseSort.sort} onSort={defenseSort.onSort}>Présence %</Th>
              </tr>
            </thead>
            <tbody>
              {defenseSort.sorted.map((p, i) => (
                <tr key={p.agent_id} style={{ background: i % 2 === 0 ? "transparent" : "rgba(255,255,255,0.015)" }}>
                  <IdentityCells player={p} />
                  <td style={TD_STYLE}>{p.defense.damage_taken.toLocaleString()}</td>
                  <td style={TD_STYLE}>{p.defense.dodges}</td>
                  <td style={TD_STYLE}>{p.defense.blocks}</td>
                  <td style={TD_STYLE}>{p.defense.interrupts}</td>
                  <td style={TD_STYLE}>{p.defense.deaths}</td>
                  <td style={TD_STYLE}>{p.defense.time_downed_ms}</td>
                  <td style={TD_STYLE}>{p.defense.cc_taken}</td>
                  <td style={TD_STYLE}>{p.defense.barrier_absorbed.toLocaleString()}</td>
                  <td style={{ ...TD_STYLE, fontVariantNumeric: "tabular-nums" }}>
                    {p.defense.presence_pct != null ? `${p.defense.presence_pct.toFixed(0)}%` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrapper>
      </section>
    </div>
  );
}
