"use client";

/**
 * v0.11.0: Fight Summary card grid — Top 3 players per category.
 *
 * Renders 6 cards (Top DPS, Top Heal, Top Strips, Top Cleanses, Top CC, Down Contrib) with
 * enriched per-player row: subgroup badge, commander crown, profession
 * icon, elite-spec label, player name, and the category value.
 *
 * Why a Client Component
 * ======================
 * The cards use ``ProfessionIcon``, ``EliteSpecIcon``, and
 * ``CommanderCrown`` from the icon library (all ``"use client"``).
 * Keeping this component client-side avoids the Server-Component
 * constraint of plain <img> tags and preserves the Tango icon
 * fallback contract.
 */

import React from "react";

import { CommanderCrown } from "@/components/icons/Commander";
import {
  EliteSpecIcon,
  ProfessionIcon,
  getEliteLabel,
  getProfessionLabel,
  parseWireFormat,
} from "@/components/icons/Professions";
import type { PlayerReadoutOut } from "@/lib/api";

/* ------------------------------------------------------------------ *
 *  Subgroup badge — renders "Sub N" with a muted colour-chip style
 * ------------------------------------------------------------------ */

function SubgroupBadge({ subgroup }: { subgroup: number }) {
  return (
    <span
      data-testid="summary-subgroup-badge"
      style={{
        display: "inline-block",
        padding: "1px 6px",
        borderRadius: 3,
        fontSize: 10,
        fontWeight: 600,
        lineHeight: "16px",
        background: "var(--surface-elevated, rgba(255,255,255,0.06))",
        border: "1px solid var(--border)",
        color: "var(--foreground)",
        opacity: 0.75,
      }}
    >
      Sub {subgroup}
    </span>
  );
}

/* ------------------------------------------------------------------ *
 *  Wire-format display helper — profession or elite label + icon
 * ------------------------------------------------------------------ */

function ProfessionOrEliteCell({
  professionWire,
  eliteSpecWire,
}: {
  professionWire: string;
  eliteSpecWire: string;
}) {
  const specParsed = parseWireFormat(eliteSpecWire);
  const hasElite =
    specParsed !== null &&
    specParsed.kind === "elite" &&
    specParsed.int !== 0;

  if (hasElite) {
    return (
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          flexShrink: 0,
        }}
        data-testid="summary-elite-cell"
        title={getEliteLabel(eliteSpecWire, professionWire) ?? undefined}
      >
        <EliteSpecIcon
          wire={eliteSpecWire}
          professionWire={professionWire}
          size={18}
        />
      </span>
    );
  }

  const profLabel = getProfessionLabel(professionWire);
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        flexShrink: 0,
      }}
      data-testid="summary-profession-cell"
      title={profLabel ?? undefined}
    >
      <ProfessionIcon wire={professionWire} size={18} />
    </span>
  );
}

/* ------------------------------------------------------------------ *
 *  One player row inside a summary card
 * ------------------------------------------------------------------ */

function SummaryPlayerRow({
  player,
  value,
  valueFormatter,
  rank,
}: {
  player: PlayerReadoutOut;
  value: string;
  valueFormatter?: (v: number) => string;
  rank: 0 | 1 | 2;
}) {
  const medal = rank === 0 ? "🥇" : rank === 1 ? "🥈" : "🥉";
  return (
    <div
      data-testid="summary-player-row"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        padding: "3px 0",
        fontSize: 13,
      }}
    >
      {/* Medal */}
      <span style={{ flexShrink: 0, width: 18, textAlign: "center" }}>
        {medal}
      </span>

      {/* Subgroup badge */}
      <SubgroupBadge subgroup={player.subgroup} />

      {/* Commander crown */}
      {player.is_commander === true && (
        <span style={{ flexShrink: 0 }}>
          <CommanderCrown size={14} />
        </span>
      )}

      {/* Profession / elite icon + label */}
      <ProfessionOrEliteCell
        professionWire={player.profession}
        eliteSpecWire={player.elite_spec}
      />

      {/* Player name — truncates with ellipsis */}
      <span
        style={{
          fontWeight: rank === 0 ? 600 : 400,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
          minWidth: 0,
        }}
        title={player.name}
      >
        {player.name}
      </span>

      {/* Spacer + value */}
      <span
        style={{
          marginLeft: "auto",
          fontWeight: 600,
          fontSize: 12,
          flexShrink: 0,
          paddingLeft: 8,
        }}
      >
        {value}
      </span>
    </div>
  );
}

/* ------------------------------------------------------------------ *
 *  Summary card — labelled container for 3 player rows
 * ------------------------------------------------------------------ */

const DEFAULT_NUMBER_FORMATTER = (v: number) => v.toLocaleString("en-US");

function SummaryCard({
  title,
  players,
  getValue,
  valueFormatter,
}: {
  title: string;
  players: PlayerReadoutOut[];
  getValue: (p: PlayerReadoutOut) => number;
  valueFormatter?: (v: number) => string;
}) {
  const sorted = [...players]
    .sort((a, b) => getValue(b) - getValue(a))
    .slice(0, 3);

  return (
    <div
      data-testid={`summary-card-${title.toLowerCase().replace(/\s+/g, "-")}`}
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: 6,
        padding: "10px 14px",
        minWidth: 200,
        flex: "0 0 auto",
      }}
    >
      {/* Card header */}
      <p
        style={{
          fontSize: 10,
          fontWeight: 700,
          opacity: 0.6,
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          margin: "0 0 6px 0",
        }}
      >
        {title}
      </p>

      {/* Player rows — compact single-line layout */}
      {sorted.map((p, i) => (
        <SummaryPlayerRow
          key={p.agent_id}
          player={p}
          value={
            (valueFormatter ?? DEFAULT_NUMBER_FORMATTER)(getValue(p))
          }
          rank={i as 0 | 1 | 2}
        />
      ))}

      {/* Empty state */}
      {sorted.length === 0 && (
        <p
          style={{
            fontSize: 12,
            opacity: 0.5,
            margin: 0,
            padding: "4px 0",
          }}
        >
          No data
        </p>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ *
 *  Main component — 4-card grid
 * ------------------------------------------------------------------ */

export function FightSummaryCards({
  players,
}: {
  players: PlayerReadoutOut[];
}) {
  if (players.length === 0) return null;

  return (
    <section
      data-testid="fight-summary"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <h2 style={{ fontSize: 18, fontWeight: 600, margin: 0 }}>
        Fight Summary
      </h2>
      <div
        style={{
          display: "flex",
          flexDirection: "row",
          flexWrap: "nowrap",
          gap: 10,
          overflowX: "auto",
          paddingBottom: 4,
        }}
      >
        <SummaryCard
          title="Top DPS"
          players={players}
          getValue={(p) => p.damage.dps_total}
        />
        <SummaryCard
          title="Top Heal"
          players={players}
          getValue={(p) => p.heal.hps}
          valueFormatter={(v) => v.toFixed(1)}
        />
        <SummaryCard
          title="Top Strips"
          players={players}
          getValue={(p) => p.damage.strips}
        />
        <SummaryCard
          title="Top Cleanses"
          players={players}
          getValue={(p) => p.heal.cleanses}
        />
        <SummaryCard
          title="Top CC"
          players={players}
          getValue={(p) => p.damage.cc_applied}
        />
        <SummaryCard
          title="Down Contrib"
          players={players}
          getValue={(p) => p.damage.down_contribution_dps}
          valueFormatter={(v) => v.toFixed(1)}
        />
      </div>
    </section>
  );
}
