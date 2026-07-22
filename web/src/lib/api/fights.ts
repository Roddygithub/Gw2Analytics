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

export interface PlayerReadoutDamageOut {
  dps_total: number;
  dps_power: number;
  dps_condi: number;
  strips: number;
  cc_applied: number;
  down_contribution_dps: number;
  kills: number;
  cleave_targets: number;
  kill_participation: number;
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
  // Plan 173: boon uptime percentages [0, 100], null when unavailable.
  might_uptime: number | null;
  fury_uptime: number | null;
  quickness_uptime: number | null;
  alacrity_uptime: number | null;
  protection_uptime: number | null;
  regeneration_uptime: number | null;
  vigor_uptime: number | null;
  aegis_uptime: number | null;
  stability_uptime: number | null;
  swiftness_uptime: number | null;
  resistance_uptime: number | null;
  resolution_uptime: number | null;
  superspeed_uptime: number | null;
  stealth_uptime: number | null;
  // Plan 173 Phase F: outgoing boon generation totals.
  outgoing_might: number | null;
  outgoing_fury: number | null;
  outgoing_quickness: number | null;
  outgoing_alacrity: number | null;
  outgoing_protection: number | null;
  outgoing_regeneration: number | null;
  outgoing_vigor: number | null;
  outgoing_aegis: number | null;
  outgoing_stability: number | null;
  outgoing_swiftness: number | null;
  outgoing_resistance: number | null;
  outgoing_resolution: number | null;
  outgoing_superspeed: number | null;
  outgoing_stealth: number | null;
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
  // Plan 173 Phase E: presence percentage [0, 100], null when unavailable.
  presence_pct: number | null;
}

export interface PlayerReadoutOut {
  agent_id: number;
  subgroup: number;
  name: string;
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

export interface PlayerPositionOut {
  account_name: string;
  name: string;
  profession: string;
  elite_spec: string;
  stack_dist: number | null;
  dist_to_com: number | null;
  dist_to_commander: number | null;
  samples: { x: number; y: number; z: number }[];
}

export interface FightPositionsOut {
  players: PlayerPositionOut[];
}

// Helper: on the client side (browser), use an empty string so the
// Next.js rewrite proxy (next.config.ts rewrites /api/v1/:path*)
// handles the request. On the server side (SSR), use API_BASE_URL
// directly (Docker DNS resolution works server-side).
function apiBase(path: string): string {
  const base = typeof window === "undefined" ? API_BASE_URL : "";
  return `${base}${path}`;
}

export async function fetchFightReadout(
  fightId: string,
): Promise<FightReadoutOut> {
  const url = apiBase(`/api/v1/fights/${encodeURIComponent(fightId)}/readout`);
  const resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  return (await resp.json()) as FightReadoutOut;
}

export async function fetchFightPositions(
  fightId: string,
): Promise<FightPositionsOut> {
  const url = apiBase(`/api/v1/fights/${encodeURIComponent(fightId)}/positions`);
  const resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  return (await resp.json()) as FightPositionsOut;
}

export async function fetchFights(): Promise<FightRow[]> {
  const resp = await fetch(apiBase("/api/v1/fights"), {
    cache: "no-store",
  });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  const data: unknown = await resp.json();
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
  const url = apiBase(`/api/v1/fights/${encodeURIComponent(fightId)}/events${
    qs ? `?${qs}` : ""
  }`);
  const resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  return (await resp.json()) as FightEventsSummaryRow;
}

export async function fetchFightSquads(
  fightId: string,
): Promise<FightSquads> {
  const url = apiBase(`/api/v1/fights/${encodeURIComponent(fightId)}/squads`);
  const resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  return (await resp.json()) as FightSquads;
}

export async function fetchFightSkills(
  fightId: string,
): Promise<FightSkills> {
  const url = apiBase(`/api/v1/fights/${encodeURIComponent(fightId)}/skills`);
  const resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  return (await resp.json()) as FightSkills;
}

export async function fetchFight(fightId: string): Promise<FightOut> {
  const url = apiBase(`/api/v1/fights/${encodeURIComponent(fightId)}`);
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
  const url = apiBase(`/api/v1/fights/${encodeURIComponent(fightId)}/players/${encodeURIComponent(accountName)}/skills`);
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
  const url = apiBase(`/api/v1/fights/${encodeURIComponent(fightId)}/timeline${
    qs ? `?${qs}` : ""
  }`);
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
  const base = typeof window === "undefined" ? API_BASE_URL : "";
  const url = `${base}/api/v1/fights/${encodeURIComponent(fightId)}/timeline/players${
    qs ? `?${qs}` : ""
  }`;
  const resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  return (await resp.json()) as FightPlayerTimeline;
}
