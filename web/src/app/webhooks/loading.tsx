import styles from "./page.module.css";

export default function WebhooksLoading() {
  return (
    <main className={styles.main}>
      <h1 className={styles.title}>Webhook DLQ</h1>
      <div className={styles.skeleton}>
        <div className={styles.skeletonTitle} />
        <div className={styles.skeletonRow} />
        <div className={styles.skeletonRow} />
        <div className={styles.skeletonRow} />
      </div>
    </main>
  );
}
