import { ApiError } from "./errors";

export interface AccountEnrichedRow {
  world_id: number;
  world_name: string;
  world_population: string;
}

/**
 * @deprecated Use {@link resolveAccountViaProxy} instead.
 * Direct gateway calls expose the API key to the browser.
 */
export async function resolveAccount(
  apiKey: string,
): Promise<AccountEnrichedRow> {
  const resp = await fetch(`${process.env.API_BASE_URL}/api/v1/account`, {
    method: "GET",
    headers: { Authorization: `Bearer ${apiKey.trim()}` },
    cache: "no-store",
  });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  return (await resp.json()) as AccountEnrichedRow;
}

/**
 * Resolve a GW2 API key via the Next.js BFF proxy at
 * ``/api/account/resolve``. The gateway URL never reaches the browser.
 */
export async function resolveAccountViaProxy(
  apiKey: string,
): Promise<AccountEnrichedRow> {
  const resp = await fetch("/api/account/resolve", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: apiKey }),
    cache: "no-store",
  });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  return (await resp.json()) as AccountEnrichedRow;
}
