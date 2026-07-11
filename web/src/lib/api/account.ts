import { API_BASE_URL } from "../env";
import { ApiError } from "./errors";

export interface AccountEnrichedRow {
  world_id: number;
  world_name: string;
  world_population: string;
}

export async function resolveAccount(
  apiKey: string,
): Promise<AccountEnrichedRow> {
  const resp = await fetch(`${API_BASE_URL}/api/v1/account`, {
    method: "GET",
    headers: { Authorization: `Bearer ${apiKey.trim()}` },
    cache: "no-store",
  });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  return (await resp.json()) as AccountEnrichedRow;
}
