/**
 * Client Component that posts a ``.zevtc`` combat log to the
 * gateway's ``/api/v1/uploads`` endpoint.
 *
 * Why client-only
 * ===============
 * The file is held in component state, sent to the gateway via
 * ``FormData`` + ``fetch``, and never persisted in localStorage /
 * cookies by this component. The gateway hashes the bytes, stores
 * the raw blob in MinIO, and queues the parser as a BackgroundTask;
 * the returned ``UploadCreatedRow`` is the lightweight envelope
 * (id + sha256 + status=pending). The parsed fight eventually
 * appears on ``/fights`` once the background parse commits.
 *
 * Why no polling
 * ==============
 * Polling the upload status here would duplicate the gateway's
 * progress surfacing and add timer + cleanup complexity. We render
 * the envelope statically; the canonical parsed result lands on
 * ``/fights`` (a Server Component that re-fetches on every visit
 * thanks to ``cache: "no-store"`` + ``force-dynamic``).
 */

"use client";

import Link from "next/link";
import { useState } from "react";

import { formatApiError, uploadLog, type UploadCreatedRow } from "@/lib/api";

import styles from "./page.module.css";

const ACCEPTED_EXT = ".zevtc";

export default function UploadPage() {
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<UploadCreatedRow | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rejected, setRejected] = useState<string | null>(null);

  // Disabled = (mid-upload) || (no file) || (extension rejected).
  // ``handleFile`` is the only path that sets ``file``, and it
  // already refuses bad extensions via the ``rejected`` flag, so
  // there's no need to re-check the extension here.
  const disabled = submitting || file === null || rejected !== null;

  function handleFile(next: File | null) {
    setRejected(null);
    setError(null);
    setResult(null);
    if (next === null) {
      setFile(null);
      return;
    }
    if (!next.name.toLowerCase().endsWith(ACCEPTED_EXT)) {
      setRejected(`Only ${ACCEPTED_EXT} files are accepted.`);
      setFile(null);
      return;
    }
    setFile(next);
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (file === null || rejected !== null) {
      return;
    }
    setSubmitting(true);
    setError(null);
    setResult(null);
    try {
      const envelope = await uploadLog(file);
      setResult(envelope);
      setFile(null);
      // Reset the native <input type="file"> so re-selecting the same
      // filename still fires a change event.
      event.currentTarget.reset();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className={styles.main}>
      <header className={styles.header}>
        <span className={styles.brand}>Combat log</span>
        <h1 className={styles.title}>Upload a .zevtc replay</h1>
        <p className={styles.lede}>
          Sends the file as <code>multipart/form-data</code> to{" "}
          <code>/api/v1/uploads</code>. The gateway hashes, stores in
          MinIO, and parses in the background; the fight appears on{" "}
          <Link href="/fights" className={styles.inlineLink}>
            /fights
          </Link>{" "}
          when parsing completes.
        </p>
      </header>

      <form
        onSubmit={handleSubmit}
        className={styles.form}
        aria-label="Upload combat log"
      >
        <label className={styles.fileLabel}>
          <span className={styles.fileLabelText}>Combat log file</span>
          <input
            type="file"
            accept={ACCEPTED_EXT}
            onChange={(event) =>
              handleFile(event.currentTarget.files?.[0] ?? null)
            }
            className={styles.fileInput}
            data-testid="file-input"
          />
          <span className={styles.fileChip} data-testid="file-chip">
            {file === null
              ? `No file selected — click to choose a ${ACCEPTED_EXT}`
              : `${file.name} · ${formatBytes(file.size)}`}
          </span>
        </label>

        {rejected !== null ? (
          <p className={styles.error} role="alert">
            {rejected}
          </p>
        ) : null}

        <button
          type="submit"
          disabled={disabled}
          className={styles.submit}
          data-testid="submit"
        >
          {submitting ? "Uploading…" : "Upload"}
        </button>
      </form>

      {result !== null ? (
        <section
          className={styles.card}
          aria-live="polite"
          data-testid="result"
        >
          <h2 className={styles.cardTitle}>Upload received</h2>
          <dl className={styles.cardGrid}>
            <dt>ID</dt>
            <dd className={styles.mono}>{result.id}</dd>
            <dt>SHA-256</dt>
            <dd className={styles.mono}>
              {result.sha256.slice(0, 8)}…{result.sha256.slice(-4)}
            </dd>
            <dt>Status</dt>
            <dd>
              <span className={styles.badge}>{result.status}</span>
              <span className={styles.faint}>
                {" "}
                · parsing in background
              </span>
            </dd>
          </dl>
          <p className={styles.cardFooter}>
            Open{" "}
            <Link href="/fights" className={styles.cardLink}>
              /fights
            </Link>{" "}
            to inspect the parsed encounter once processing finishes.
          </p>
        </section>
      ) : null}

      {error !== null ? (
        <p
          className={styles.error}
          role="alert"
          data-testid="error"
        >
          {error}
        </p>
      ) : null}
    </main>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KiB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}
