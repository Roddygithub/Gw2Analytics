import { API_BASE_URL } from "../env";
import { ApiError } from "./errors";

export interface WebhookDlqRow {
  id: string;
  subscription_id: string;
  upload_id: string;
  last_error: string | null;
  moved_to_dlq_at: string;
}

export async function fetchWebhookDeliveries(
  opts: { subscriptionId?: string; limit?: number; offset?: number } = {},
): Promise<WebhookDlqRow[]> {
  const params = new URLSearchParams();
  if (opts.subscriptionId !== undefined) {
    params.set("subscription_id", opts.subscriptionId);
  }
  if (opts.limit !== undefined) {
    params.set("limit", String(opts.limit));
  }
  if (opts.offset !== undefined) {
    params.set("offset", String(opts.offset));
  }
  const qs = params.toString();
  const url = `${API_BASE_URL}/api/v1/webhooks/dlq${qs ? `?${qs}` : ""}`;
  const resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  const rows: unknown = await resp.json();
  if (!Array.isArray(rows)) {
    throw new ApiError(500, "upstream returned non-array");
  }
  return rows as WebhookDlqRow[];
}

export async function replayDlq(deliveryId: string): Promise<void> {
  const url = `${API_BASE_URL}/api/v1/webhooks/dlq/${encodeURIComponent(
    deliveryId,
  )}/replay`;
  const resp = await fetch(url, { method: "POST", cache: "no-store" });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
}
