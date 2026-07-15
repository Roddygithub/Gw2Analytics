import { API_BASE_URL } from "../env";
import { ApiError } from "./errors";

export interface FightRow {
  id: string;
  build_version: string;
  encounter_id: number;
  agent_count: number;
  started_at: string;
  game_type: number;
}

export interface TargetDpsRow {
  target_agent_id: number;
  total_damage: number;
  dps: number;
  name: string | null;
}

export interface TargetHealingRow {
  target_agent_id: number;
  total_healing: number;
  hps: number;
  name: string | null;
}

export interface TargetBuffRemovalRow {
  target_agent_id: number;
  total_buff_removal: number;
  bps: number;
  name: string | null;
}

export interface AgentOut {
  agent_id: number;
  name: string;
  profession: string;
  elite_spec: string;
  is_player: boolean;
  account_name: string | null;
  subgroup: string | null;
}

export interface SkillOut {
  id: number;
  name: string;
}

export interface FightOut {
  id: string;
  build_version: string;
  encounter_id: number;
  agent_count: number;
  started_at: string;
  game_type: number;
  agents: AgentOut[];
  skills: SkillOut[];
}

export interface EventBucket {
  start_ms: number;
  end_ms: number;
  damage_total: number;
  healing_total: number;
  event_count: number;
}

export interface FightEventsSummaryRow {
  fight_id: string;
  duration_s: number;
  target_dps: TargetDpsRow[];
  target_healing: TargetHealingRow[];
  target_buff_removal: TargetBuffRemovalRow[];
  event_windows: EventBucket[];
}

export interface SquadRollupRow {
  subgroup: string;
  total_damage: number;
  total_healing: number;
  total_buff_removal: number;
  dps: number;
  hps: number;
  bps: number;
}

export interface FightSquads {
  fight_id: string;
  duration_s: number;
  squads: SquadRollupRow[];
}

export interface SkillUsageRow {
  skill_id: number;
  skill_name: string;
  hit_count: number;
  total_damage: number;
  total_healing: number;
  total_buff_removal: number;
}

export interface FightSkills {
  fight_id: string;
  skills: SkillUsageRow[];
}

export interface PlayerSkillUsageRow {
  skill_id: number;
  skill_name: string;
  hit_count: number;
  total_damage: number;
  total_healing: number;
  total_buff_removal: number;
}

export interface PlayerSkillLoadout {
  profession: string;
  elite_spec: string;
  /** Optional: parser-layer equipped-skill extraction is deferred to v0.11.0;
   * the backend always emits ``[]`` today (the V1 stub) but optionality
   * keeps the contract forward-compat with future wire-format changes. */
  equipped_skill_ids?: number[];
}

export interface PlayerSkills {
  fight_id: string;
  account_name: string;
  agent_id: number;
  loadout: PlayerSkillLoadout;
  skills: PlayerSkillUsageRow[];
}

export interface PerFightTimelinePoint {
  window_start_ms: number;
  window_end_ms: number;
  total_damage: number;
  total_healing: number;
  total_buff_removal: number;
}

export interface FightTimeline {
  fight_id: string;
  window_s: number;
  duration_s: number;
  points: PerFightTimelinePoint[];
}

export interface PerPlayerTimelinePoint {
  window_start_ms: number;
  window_end_ms: number;
  total_damage: number;
  total_healing: number;
  total_buff_removal: number;
}

export interface PerPlayerTimelineSeries {
  account_name: string;
  name: string;
  points: PerPlayerTimelinePoint[];
}

export interface FightPlayerTimeline {
  fight_id: string;
  window_s: number;
  duration_s: number;
  series: PerPlayerTimelineSeries[];
}

// ============================================================================
// Tour 6 Wave 7 (Workstream F): Combat-readout wire-shape types.
//
// Mirrors apps/api/src/gw2analytics_api/schemas/fight.py :: PlayerReadout{Damage,Heal,Boons,Defense}Out + PlayerReadoutOut + FightReadoutOut.
//
// Note on the `subgroup` type drift: the existing AgentOut schema uses
// `subgroup: string | null` (the legacy per-target contract) while
// PlayerReadoutOut uses `subgroup: int` (the per-player readout contract).
// Per thinker's recommendation A, we ACCEPT the type drift at the
// consumer boundary rather than coerce AgentOut to int — the existing
// TargetRollupsGrid + SquadRollupsGrid depend on string-typed subgroups
// (their `subgroup` column is a string label), so changing AgentOut
// would break their rendering. The Readout grid maps int -> `Sub N`
// label inline.
// ============================================================================

export interface PlayerReadoutDamageOut {
  dps_total: number;
  dps_power: number;
  dps_condi: number;
  strips: number;
  cc_applied: number;
  down_contribution_dps: number;
  kills: number;
}

export interface PlayerReadoutHealOut {
  heal_total: number;
  hps: number;
  barrier_total: number;
  barrier_ps: number;
  cleanses: number;
  stun_breaks: number;
}

export interface PlayerReadoutBoonsOut {
  boons_out_rate: number;
  boons_in_rate: number;
  stability_out: number;
  alacrity_out: number;
  resistance_out: number;
  aegis_out: number;
  superspeed_out: number;
  stealth_out: number;
  other_boons_out: Record<string, number>;
}

export interface PlayerReadoutDefenseOut {
  damage_taken: number;
  cc_taken: number;
  deaths: number;
  time_downed_ms: number;
  dodges: number;
  blocks: number;
  interrupts: number;
  barrier_absorbed: number;
}

export interface PlayerReadoutOut {
  agent_id: number;
  subgroup: number;
  name: string;
  // Tour 6 v0.10.24-pre follow-up wire-contract widening: the
  // account_name is now string | null (the schema widening
  // completed in lockstep with the apps/api schema change). The
  // arcdps None-vs-empty-string distinction now survives the wire
  // so consumers can attribute the two cases independently. The
  // Tier-2 consumers (PlayersGrid, CrossAccountTimelineChart,
  // PerPlayerTimelineChart) handle the null path explicitly.
  account_name: string | null;
  profession: string;
  elite_spec: string;
  is_commander: boolean;
  roles: string[];
  damage: PlayerReadoutDamageOut;
  heal: PlayerReadoutHealOut;
  boons: PlayerReadoutBoonsOut;
  defense: PlayerReadoutDefenseOut;
}

export interface FightReadoutOut {
  fight_id: string;
  duration_s: number;
  players: PlayerReadoutOut[];
}

export async function fetchFightReadout(
  fightId: string,
): Promise<FightReadoutOut> {
  const url = `${API_BASE_URL}/api/v1/fights/${encodeURIComponent(fightId)}/readout`;
  const resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  return (await resp.json()) as FightReadoutOut;
}

export async function fetchFights(): Promise<FightRow[]> {
  const resp = await fetch(`${API_BASE_URL}/api/v1/fights`, {
    cache: "no-store",
  });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  const data: unknown = await resp.json();
  // v0.10.12: the backend returns a paginated page object
  // { fights, limit, offset }; the fights array is what the
  // grid consumes.
  const page =
    data !== null && typeof data === "object" && "fights" in data
      ? (data as { fights: unknown }).fights
      : data;
  if (!Array.isArray(page)) {
    throw new ApiError(500, "upstream returned non-array");
  }
  return page as FightRow[];
}

export async function fetchFightEvents(
  fightId: string,
  opts: { windowS?: number } = {},
): Promise<FightEventsSummaryRow> {
  const params = new URLSearchParams();
  if (opts.windowS !== undefined) {
    params.set("window_s", String(opts.windowS));
  }
  const qs = params.toString();
  const url = `${API_BASE_URL}/api/v1/fights/${encodeURIComponent(fightId)}/events${
    qs ? `?${qs}` : ""
  }`;
  const resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  return (await resp.json()) as FightEventsSummaryRow;
}

export async function fetchFightSquads(
  fightId: string,
): Promise<FightSquads> {
  const url = `${API_BASE_URL}/api/v1/fights/${encodeURIComponent(fightId)}/squads`;
  const resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  return (await resp.json()) as FightSquads;
}

export async function fetchFightSkills(
  fightId: string,
): Promise<FightSkills> {
  const url = `${API_BASE_URL}/api/v1/fights/${encodeURIComponent(fightId)}/skills`;
  const resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  return (await resp.json()) as FightSkills;
}

export async function fetchFight(fightId: string): Promise<FightOut> {
  // Tour 4 v0.10.13 plan 044: backend ``GET /api/v1/fights/{id}``
  // (the existing ::func::``get_fight`` route handler) returns the
  // full :class::``OrmFight`` row + the embedded :class::``OrmFightAgent``
  // row list required for the per-player dropdown. The page wires
  // this into the ``?account=`` URL search-param filter contract.
  const url = `${API_BASE_URL}/api/v1/fights/${encodeURIComponent(fightId)}`;
  const resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  return (await resp.json()) as FightOut;
}

export async function fetchFightPlayerSkills(
  fightId: string,
  accountName: string,
): Promise<PlayerSkills> {
  const url = `${API_BASE_URL}/api/v1/fights/${encodeURIComponent(fightId)}/players/${encodeURIComponent(accountName)}/skills`;
  const resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  return (await resp.json()) as PlayerSkills;
}

export async function fetchFightTimeline(
  fightId: string,
  opts: { windowS?: number } = {},
): Promise<FightTimeline> {
  const params = new URLSearchParams();
  if (opts.windowS !== undefined) {
    params.set("window_s", String(opts.windowS));
  }
  const qs = params.toString();
  const url = `${API_BASE_URL}/api/v1/fights/${encodeURIComponent(fightId)}/timeline${
    qs ? `?${qs}` : ""
  }`;
  const resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  return (await resp.json()) as FightTimeline;
}

export async function fetchFightPlayerTimeline(
  fightId: string,
  opts: { windowS?: number } = {},
): Promise<FightPlayerTimeline> {
  const params = new URLSearchParams();
  if (opts.windowS !== undefined) {
    params.set("window_s", String(opts.windowS));
  }
  const qs = params.toString();
  const url = `${API_BASE_URL}/api/v1/fights/${encodeURIComponent(fightId)}/timeline/players${
    qs ? `?${qs}` : ""
  }`;
  const resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  return (await resp.json()) as FightPlayerTimeline;
}
