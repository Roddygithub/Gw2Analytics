"use client";

/**
 * Native HTML table component for the fight compare page.
 *
 * Replaces the 4 AG Grid ``PlayerReadout*`` components with
 * native HTML tables that match the ``ReadoutTabClient`` style.
 * Sortable by clicking column headers (per-table independent sort).
 *
 * Boon icons (14 official GW2 icons) are rendered in the boon
 * table headers (single source of truth: ``shared/readoutTableParts``).
 */
import React from "react";

import type { PlayerReadoutOut } from "@/lib/api";
import {
  TABLE_STYLE,
  TH_STYLE,
  TD_STYLE,
  BOONS,
  useSortedPlayers,
  DpsBar,
  HealBar,
  Th,
  IdentityCells,
  TableWrapper,
} from "@/lib/readoutTableParts";

/* ------------------------------------------------------------------ *
 *  Main component
 * ------------------------------------------------------------------ */

export type CompareTableKind = "damage" | "heal" | "boons" | "defense";

const TABLE_TITLE: Record<CompareTableKind, string> = {
  damage: "Dégâts",
  heal: "Soins",
  boons: "Boons",
  defense: "Défense & Positionnement",
};

interface CompareReadoutTableProps {
  kind: CompareTableKind;
  players: PlayerReadoutOut[];
}

export function CompareReadoutTable({ kind, players }: CompareReadoutTableProps) {
  if (players.length === 0) {
    return (
      <div style={{ padding: "12px 16px", border: "1px solid var(--border)", borderRadius: 4, color: "var(--foreground)", opacity: 0.7 }}>
        Aucun joueur dans ce tableau.
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <h4 style={{ fontSize: 13, fontWeight: 600, margin: 0, opacity: 0.8 }}>
        {TABLE_TITLE[kind]}
      </h4>
      <TableWrapper maxHeight={400}>
        {kind === "damage" && <DamageTable players={players} />}
        {kind === "heal" && <HealTable players={players} />}
        {kind === "boons" && <BoonsTable players={players} />}
        {kind === "defense" && <DefenseTable players={players} />}
      </TableWrapper>
    </div>
  );
}

/* ------------------------------------------------------------------ *
 *  Damage table
 * ------------------------------------------------------------------ */

function DamageTable({ players }: { players: PlayerReadoutOut[] }) {
  const { sorted, sort, onSort } = useSortedPlayers(players, "dps_total", "desc");

  return (
    <table style={TABLE_STYLE}>
      <thead>
        <tr>
          <Th field="subgroup" currentSort={sort} onSort={onSort}>Groupe</Th>
          <Th field="name" currentSort={sort} onSort={onSort}>Nom</Th>
          <Th field="" currentSort={null} onSort={() => {}} style={{ cursor: "default" }}>Spé</Th>
          <Th field="" currentSort={null} onSort={() => {}} style={{ cursor: "default", width: 40 }}>Cmd</Th>
          <Th field="" currentSort={null} onSort={() => {}} style={{ cursor: "default" }}>Rôles</Th>
          <Th field="dps_total" currentSort={sort} onSort={onSort} style={{ minWidth: 180 }}>DPS (power / condi)</Th>
          <Th field="strips" currentSort={sort} onSort={onSort}>Strips</Th>
          <Th field="cc_applied" currentSort={sort} onSort={onSort}>CC</Th>
          <Th field="down_contrib" currentSort={sort} onSort={onSort}>Down DPS</Th>
          <Th field="cleave" currentSort={sort} onSort={onSort}>Cleave</Th>
          <Th field="kills" currentSort={sort} onSort={onSort}>Kills</Th>
          <Th field="deaths" currentSort={sort} onSort={onSort}>Morts</Th>
          <Th field="kill_part" currentSort={sort} onSort={onSort}>Kill Part</Th>
        </tr>
      </thead>
      <tbody>
        {sorted.map((p, i) => (
          <tr key={p.agent_id} style={{ background: i % 2 === 0 ? "transparent" : "var(--row-stripe)" }}>
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
  );
}

/* ------------------------------------------------------------------ *
 *  Heal table
 * ------------------------------------------------------------------ */

function HealTable({ players }: { players: PlayerReadoutOut[] }) {
  const { sorted, sort, onSort } = useSortedPlayers(players, "hps", "desc");

  return (
    <table style={TABLE_STYLE}>
      <thead>
        <tr>
          <Th field="subgroup" currentSort={sort} onSort={onSort}>Groupe</Th>
          <Th field="name" currentSort={sort} onSort={onSort}>Nom</Th>
          <Th field="" currentSort={null} onSort={() => {}} style={{ cursor: "default" }}>Spé</Th>
          <Th field="" currentSort={null} onSort={() => {}} style={{ cursor: "default", width: 40 }}>Cmd</Th>
          <Th field="" currentSort={null} onSort={() => {}} style={{ cursor: "default" }}>Rôles</Th>
          <Th field="hps" currentSort={sort} onSort={onSort} style={{ minWidth: 180 }}>Heal / Barrier</Th>
          <Th field="cleanses" currentSort={sort} onSort={onSort}>Cleanses</Th>
          <Th field="stun_breaks" currentSort={sort} onSort={onSort}>Breakstun</Th>
        </tr>
      </thead>
      <tbody>
        {sorted.map((p, i) => (
          <tr key={p.agent_id} style={{ background: i % 2 === 0 ? "transparent" : "var(--row-stripe)" }}>
            <IdentityCells player={p} />
            <td style={TD_STYLE}><HealBar hps={p.heal.hps} bps={p.heal.barrier_ps} total={p.heal.heal_total ?? 0} /></td>
            <td style={TD_STYLE}>{p.heal.cleanses}</td>
            <td style={TD_STYLE}>{p.heal.stun_breaks}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/* ------------------------------------------------------------------ *
 *  Boons table (with official GW2 icons)
 * ------------------------------------------------------------------ */

function BoonsTable({ players }: { players: PlayerReadoutOut[] }) {
  const { sorted, sort, onSort } = useSortedPlayers(players, "boon_in_might", "desc");

  return (
    <table style={TABLE_STYLE}>
      <thead>
        <tr>
          <Th field="subgroup" currentSort={sort} onSort={onSort} style={{ minWidth: 50 }}>Groupe</Th>
          <Th field="name" currentSort={sort} onSort={onSort}>Nom</Th>
          <Th field="" currentSort={null} onSort={() => {}} style={{ cursor: "default" }}>Spé</Th>
          <Th field="" currentSort={null} onSort={() => {}} style={{ cursor: "default", width: 40 }}>Cmd</Th>
          <Th field="" currentSort={null} onSort={() => {}} style={{ cursor: "default" }}>Rôles</Th>
          {BOONS.map((b) => (
            <th key={b.key} style={{ ...TH_STYLE, textAlign: "center", cursor: "default" }} colSpan={2} title={b.label}>
              {b.iconFile ? (
                <img
                  src={`/icons/boons/${b.iconFile}_tango.png`}
                  alt={b.label}
                  width={22}
                  height={22}
                  style={{ display: "block", margin: "0 auto" }}
                  onError={(e) => { e.currentTarget.style.display = "none"; }}
                />
              ) : (
                b.label
              )}
            </th>
          ))}
        </tr>
        <tr>
          {BOONS.map((b) => (
            <React.Fragment key={b.key}>
              <Th field={`boon_in_${b.key}`} currentSort={sort} onSort={onSort} style={{ width: 42, textAlign: "center" }}>
                In
              </Th>
              <Th field={`boon_out_${b.key}`} currentSort={sort} onSort={onSort} style={{ width: 42, textAlign: "center" }}>
                Out
              </Th>
            </React.Fragment>
          ))}
        </tr>
      </thead>
      <tbody>
        {sorted.map((p, i) => (
          <tr key={p.agent_id} style={{ background: i % 2 === 0 ? "transparent" : "var(--row-stripe)" }}>
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
  );
}

/* ------------------------------------------------------------------ *
 *  Defense table
 * ------------------------------------------------------------------ */

function DefenseTable({ players }: { players: PlayerReadoutOut[] }) {
  const { sorted, sort, onSort } = useSortedPlayers(players, "damage_taken", "desc");

  return (
    <table style={TABLE_STYLE}>
      <thead>
        <tr>
          <Th field="subgroup" currentSort={sort} onSort={onSort}>Groupe</Th>
          <Th field="name" currentSort={sort} onSort={onSort}>Nom</Th>
          <Th field="" currentSort={null} onSort={() => {}} style={{ cursor: "default" }}>Spé</Th>
          <Th field="" currentSort={null} onSort={() => {}} style={{ cursor: "default", width: 40 }}>Cmd</Th>
          <Th field="" currentSort={null} onSort={() => {}} style={{ cursor: "default" }}>Rôles</Th>
          <Th field="damage_taken" currentSort={sort} onSort={onSort}>Dmg reçu</Th>
          <Th field="dodges" currentSort={sort} onSort={onSort}>Esquives</Th>
          <Th field="blocks" currentSort={sort} onSort={onSort}>Blocages</Th>
          <Th field="interrupts" currentSort={sort} onSort={onSort}>Interrupt</Th>
          <Th field="deaths" currentSort={sort} onSort={onSort}>Morts</Th>
          <Th field="time_downed" currentSort={sort} onSort={onSort}>Down (ms)</Th>
          <Th field="cc_taken" currentSort={sort} onSort={onSort}>CC reçus</Th>
          <Th field="barrier_absorbed" currentSort={sort} onSort={onSort}>Barrier abs.</Th>
          <Th field="presence_pct" currentSort={sort} onSort={onSort}>Présence %</Th>
          <Th field="dist_to_commander" currentSort={sort} onSort={onSort}>Dist. Cmd</Th>
          <Th field="kill_part" currentSort={sort} onSort={onSort}>Kill Part</Th>
        </tr>
      </thead>
      <tbody>
        {sorted.map((p, i) => (
          <tr key={p.agent_id} style={{ background: i % 2 === 0 ? "transparent" : "var(--row-stripe)" }}>
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
            <td style={{ ...TD_STYLE, fontVariantNumeric: "tabular-nums" }}>
              {p.defense.dist_to_commander != null ? p.defense.dist_to_commander.toFixed(0) : "—"}
            </td>
            <td style={TD_STYLE}>{p.defense.kill_participation}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
