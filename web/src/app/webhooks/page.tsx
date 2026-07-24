/**
 * v0.10.25 PR2 webhook management page — extends the pre-PR2
 * DLQ-only surface with the full subscription lifecycle:
 *
 *  - \`CreateWebhookPanel\` (Client Component) renders an inline
 *    3-phase state machine (closed / form / reveal) so the
 *    analyst can register a new subscription without leaving
 *    the page. The :class:\`CreateWebhookPanel\` docstring
 *    documents the rationale for the inline reveal flow
 *    (one-shot plaintext secret, Fernet envelope at rest).
 *
 *  - \`WebhookSubscriptionsGrid\` (Client Component, AG Grid)
 *    renders the active subscriptions list with a per-row
 *    \`Revoke\` action that delegates to
 *    :func:\`revokeWebhook\` + \`router.refresh()\`. The
 *    subscriptions list is the operator's primary surface; the
 *    DLQ below it is the second-order view (failed deliveries
 *    belonging to a subscription).
 *
 * Why parallel \`Promise.all\` for the two fetches
 * =================================================
 * The subscriptions list and the DLQ are independent reads
 * from two unrelated tables. A sequential second fetch would
 * double the round-trip latency; \`Promise.all\` shortens the
 * critical path from \`2 \u00d7 ttfb\` to \`max(ttfb_sub,
 * ttfb_dlq)\`. Each catch is isolated so a single failed fetch
 * still renders the other surface (a DLQ outage is operational
 * noise, not a full-page error).
 *
 * Why no auth gate
 * ================
 * The whole app is unauthenticated; any visitor can hit
 * \`/api/v1/webhooks\`. A future auth cycle can wrap this
 * server component in \`if (!session) return <RedirectToLogin
 * />\` without touching the client child components
 * (\`CreateWebhookPanel\` + \`WebhookSubscriptionsGrid\` + DLQ
 * grid are all self-contained).
 *
 * Why \`force-dynamic\`
 * ====================
 * Bypasses Next.js's static caching so newly registered
 * subscriptions + newly delivered/replayed rows surface on the
 * next render without a 60s revalidate sweep. Standard for
 * read-write ops surfaces.
 */

import {
  fetchWebhookDeliveries,
  fetchWebhookSubscriptions,
  formatApiError,
  type WebhookDlqRow,
  type WebhookSubscriptionRow,
} from "@/lib/api";
import { WebhookDlqGrid } from "@/components/WebhookDlqGrid";
import { WebhookSubscriptionsGrid } from "@/components/WebhookSubscriptionsGrid";
import { CreateWebhookPanel } from "@/components/CreateWebhookPanel";

import styles from "./page.module.css";

export const dynamic = "force-dynamic";

export default async function WebhooksPage() {
  const [subsResult, dlqResult] = await Promise.allSettled([
    fetchWebhookSubscriptions(),
    fetchWebhookDeliveries(),
  ]);

  let subscriptions: WebhookSubscriptionRow[] = [];
  let subscriptionsError: string | null = null;
  if (subsResult.status === "fulfilled") {
    subscriptions = subsResult.value;
  } else {
    subscriptionsError = formatApiError(subsResult.reason);
  }

  let dlq: WebhookDlqRow[] = [];
  let dlqError: string | null = null;
  if (dlqResult.status === "fulfilled") {
    dlq = dlqResult.value;
  } else {
    dlqError = formatApiError(dlqResult.reason);
  }

  return (
    <main className={styles.main}>
      <h1 className={styles.title}>Webhooks</h1>

      <section aria-label="Subscriptions" className={styles.section}>
        <h2 className={styles.sectionTitle}>Subscriptions</h2>
        <p className={styles.sectionLede}>
          Registered webhook endpoints. The plaintext secret is
          shown only when a subscription is first created; copy it
          then. Click on any subscription below to inspect or
          revoke it.
        </p>
        <CreateWebhookPanel />
        {subscriptionsError ? (
          <p className={styles.errorText} role="alert">
            Error: {subscriptionsError}
          </p>
        ) : (
          <WebhookSubscriptionsGrid rows={subscriptions} />
        )}
      </section>

      <section aria-label="Webhook DLQ" className={styles.section}>
        <h2 className={styles.sectionTitle}>DLQ (failed deliveries)</h2>
        <p className={styles.sectionLede}>
          Webhook deliveries that exhausted retries. Each row
          offers a one-shot replay.
        </p>
        {dlqError ? (
          <p className={styles.errorText} role="alert">
            Error: {dlqError}
          </p>
        ) : (
          <WebhookDlqGrid rows={dlq} />
        )}
      </section>
    </main>
  );
}
