import { fetchWebhookDeliveries, type WebhookDlqRow } from "@/lib/api";
import { WebhookDlqGrid } from "@/components/WebhookDlqGrid";

import styles from "./page.module.css";

export const dynamic = "force-dynamic";

export default async function WebhooksPage() {
  let rows: WebhookDlqRow[] = [];
  let error: string | null = null;

  try {
    rows = await fetchWebhookDeliveries();
  } catch (err) {
    error = err instanceof Error ? err.message : String(err);
  }

  return (
    <main className={styles.main}>
      <h1 className={styles.title}>Webhook DLQ</h1>
      {error ? (
        <p className={styles.errorText}>Error: {error}</p>
      ) : (
        <WebhookDlqGrid rows={rows} />
      )}
    </main>
  );
}
