import Link from "next/link";
import { displayedApiBaseUrl } from "@/lib/env";
import styles from "./page.module.css";

export default function Home() {
  return (
    <div className={styles.page}>
      <section className={styles.hero}>
        <span className={styles.brand}>Guild Wars 2 · WvW</span>
        <h1 className={styles.title}>GW2Analytics</h1>
        <p className={styles.tagline}>
          Independent combat analytics: parse <code>.zevtc</code>{" "}
          logs locally, aggregate fights, enrich with the official v2
          API.
        </p>
      </section>

      <nav className={styles.cards}>
        <Link className={styles.card} href="/fights">
          <span className={styles.cardTitle}>Browse fights</span>
          <span className={styles.cardBody}>
            Inspect parsed encounters, agents, and skill tables in an
            AG&nbsp;Grid.
          </span>
          <span className={styles.cardArrow}>Open &rarr;</span>
        </Link>
        <Link className={styles.card} href="/account">
          <span className={styles.cardTitle}>Resolve API key</span>
          <span className={styles.cardBody}>
            Submit a GW2 API key to enrich an upload with{" "}
            <code>(world_id, world_name, world_population)</code>.
          </span>
          <span className={styles.cardArrow}>Open &rarr;</span>
        </Link>
      </nav>

      <p className={styles.footer}>
        Stateless frontend &middot; data sourced from{" "}
        <code>{displayedApiBaseUrl}</code>.
      </p>
    </div>
  );
}
