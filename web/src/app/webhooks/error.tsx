"use client";

import { useEffect } from "react";

import styles from "./page.module.css";

export default function WebhooksError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
     
    console.error("Webhooks page error:", error);
  }, [error]);

  return (
    <main className={styles.main}>
      <h1 className={styles.title}>Webhook DLQ</h1>
      <p className={styles.errorText}>
        Something went wrong while loading the failed deliveries.
      </p>
      <button type="button" onClick={reset} className={styles.retryButton}>
        Try again
      </button>
    </main>
  );
}
