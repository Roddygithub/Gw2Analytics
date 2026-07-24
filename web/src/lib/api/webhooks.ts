import { API_BASE_URL } from "../env";
import { ApiError } from "./errors";

export interface WebhookDlqRow {
  id: string;
  subscription_id: string;
  upload_id: string;
  last_error: string | null;
  moved_to_dlq_at: string;
}

/**
 * PR2 wire-shape mirror of the OpenAPI-generated
 * ``WebhookSubscriptionOut`` schema. ``created_at`` is a
 * date-time string (FastAPI serialises ``datetime`` as ISO-8601);
 * the frontend renders it via ``Date.toLocaleString``. ``filter``
 * is a free-form object (the Python ORM column name is ``filter``
 * which shadows the builtin; the wire schema reuses the
 * ``filter_payload`` Python attr name as the field key).
 * ``description`` is optional and may be ``null`` (the Pydantic
 * model defaults to ``None``).
 */
export interface WebhookSubscriptionRow {
  id: string;
  url: string;
  filter: Record<string, unknown> | null;
  description: string | null;
  created_at: string;
}

/**
 * One-shot create response: identical to
 * :class:`WebhookSubscriptionRow` PLUS the plaintext ``secret``
 * which the backend emits ONLY on the 201 response (Fernet
 * envelope encryption-at-rest for everything past the create
 * call per plan 031). Callers MUST surface the ``secret`` in a
 * dedicated acknowledgement UI before discarding the response
 * to avoid the one-shot-loss bug.
 */
export interface WebhookSubscriptionCreatedRow extends WebhookSubscriptionRow {
  secret: string;
}

export interface CreateWebhookPayload {
  url: string;
  description?: string | null;
  filter?: Record<string, unknown> | null;
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

export async function fetchWebhookSubscriptions(
  opts: { limit?: number; offset?: number } = {},
): Promise<WebhookSubscriptionRow[]> {
  const params = new URLSearchParams();
  if (opts.limit !== undefined) {
    params.set("limit", String(opts.limit));
  }
  if (opts.offset !== undefined) {
    params.set("offset", String(opts.offset));
  }
  const qs = params.toString();
  const url = `${API_BASE_URL}/api/v1/webhooks${qs ? `?${qs}` : ""}`;
  const resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  const rows: unknown = await resp.json();
  if (!Array.isArray(rows)) {
    throw new ApiError(500, "upstream returned non-array");
  }
  return rows as WebhookSubscriptionRow[];
}

/**
 * Register a new webhook subscription. The backend returns
 * ``201 Created`` with the plaintext ``secret`` which is
 * Fernet-encrypted-at-rest for any subsequent fetch (one-shot
 * plaintext surface). The caller is responsible for surfacing
 * the secret in an acknowledgement UI before discarding the
 * response.
 */
export async function createWebhook(
  payload: CreateWebhookPayload,
): Promise<WebhookSubscriptionCreatedRow> {
  const url = `${API_BASE_URL}/api/v1/webhooks`;
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      url: payload.url,
      description: payload.description ?? null,
      filter: payload.filter ?? {},
    }),
    cache: "no-store",
  });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  return (await resp.json()) as WebhookSubscriptionCreatedRow;
}

/**
 * Idempotent soft-delete: the backend responds 204 on success AND
 * on a previously-revoked subscription. A genuine unknown-id
 * 404 propagates as a real ``ApiError(404, ...)`` so the UI can
 * surface the orphaned-row case instead of silently no-op-ing.
 */
export async function revokeWebhook(subscriptionId: string): Promise<void> {
  const url = `${API_BASE_URL}/api/v1/webhooks/${encodeURIComponent(
    subscriptionId,
  )}`;
  const resp = await fetch(url, { method: "DELETE", cache: "no-store" });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
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
