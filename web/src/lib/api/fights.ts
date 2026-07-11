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

export async function fetchFights(): Promise<FightRow[]> {
  const resp = await fetch(`${API_BASE_URL}/api/v1/fights`, {
    cache: "no-store",
  });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  const rows: unknown = await resp.json();
  if (!Array.isArray(rows)) {
    throw new ApiError(500, "upstream returned non-array");
  }
  return rows as FightRow[];
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
