import { API_BASE_URL } from "../env";
import { ApiError } from "./errors";

export interface PlayerListRow {
  account_name: string;
  name: string;
  profession: string;
  elite_spec: string;
  fights_attended: number;
  total_damage: number;
  total_healing: number;
  total_buff_removal: number;
}

export interface PerFightBreakdownRow {
  fight_id: string;
  started_at: string;
  total_damage: number;
  total_healing: number;
  total_buff_removal: number;
}

export interface PlayerProfile {
  account_name: string;
  name: string;
  profession: string;
  elite_spec: string;
  fights_attended: number;
  total_damage: number;
  total_healing: number;
  total_buff_removal: number;
  attended_fight_ids: string[];
  per_fight_breakdown: PerFightBreakdownRow[];
}

export interface PlayerTimelinePoint {
  fight_id: string;
  started_at: string;
  total_damage: number;
  total_healing: number;
  total_buff_removal: number;
}

export interface PlayerTimeline {
  account_name: string;
  total: number;
  limit: number;
  offset: number;
  bucket: "fight" | "day";
  tz: string;
  points: PlayerTimelinePoint[];
}

export interface CrossAccountTimelinePoint {
  fight_id: string;
  started_at: string;
  total_damage: number;
  total_healing: number;
  total_buff_removal: number;
}

export interface CrossAccountTimelineSeries {
  account_name: string;
  name: string;
  points: CrossAccountTimelinePoint[];
}

export async function fetchPlayers(
  opts: { limit?: number; offset?: number; profession?: string } = {},
): Promise<PlayerListRow[]> {
  const params = new URLSearchParams();
  if (opts.limit !== undefined) params.set("limit", String(opts.limit));
  if (opts.offset !== undefined) params.set("offset", String(opts.offset));
  if (opts.profession !== undefined) params.set("profession", opts.profession);
  const qs = params.toString();
  const url = `${API_BASE_URL}/api/v1/players${qs ? `?${qs}` : ""}`;
  const resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  const rows: unknown = await resp.json();
  if (!Array.isArray(rows)) {
    throw new ApiError(500, "upstream returned non-array");
  }
  return rows as PlayerListRow[];
}

export async function fetchPlayer(
  accountName: string,
): Promise<PlayerProfile> {
  const url = `${API_BASE_URL}/api/v1/players/${encodeURIComponent(accountName)}`;
  const resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  return (await resp.json()) as PlayerProfile;
}

export async function fetchPlayerTimeline(
  accountName: string,
  opts: {
    limit?: number;
    offset?: number;
    bucket?: "fight" | "day";
    tz?: string;
  } = {},
): Promise<PlayerTimeline> {
  const params = new URLSearchParams();
  if (opts.limit !== undefined) params.set("limit", String(opts.limit));
  if (opts.offset !== undefined) params.set("offset", String(opts.offset));
  if (opts.bucket !== undefined) params.set("bucket", opts.bucket);
  if (opts.tz !== undefined) params.set("tz", opts.tz);
  const qs = params.toString();
  const url = `${API_BASE_URL}/api/v1/players/${encodeURIComponent(accountName)}/timeline${
    qs ? `?${qs}` : ""
  }`;
  const resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  return (await resp.json()) as PlayerTimeline;
}

export async function fetchPlayerCompareTimeline(
  accounts: string[],
  opts: { bucket?: "fight" | "day"; tz?: string } = {},
): Promise<CrossAccountTimelineSeries[]> {
  const params = new URLSearchParams();
  for (const acct of accounts) {
    params.append("accounts", acct);
  }
  if (opts.bucket !== undefined) params.set("bucket", opts.bucket);
  if (opts.tz !== undefined) params.set("tz", opts.tz);
  const qs = params.toString();
  const url = `${API_BASE_URL}/api/v1/players/compare/timeline?${qs}`;
  const resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  const rows: unknown = await resp.json();
  if (!Array.isArray(rows)) {
    throw new ApiError(500, "upstream returned non-array");
  }
  return rows as CrossAccountTimelineSeries[];
}
