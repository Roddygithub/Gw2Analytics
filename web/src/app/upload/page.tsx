/**
 * Client Component that posts a ``.zevtc`` combat log to the
 * gateway's ``/api/v1/uploads`` endpoint through a 3-step
 * onboarding wizard:
 *
 *  1. **Pick** -- file input + client-side extension guard.
 *     Disabled until a valid file is dropped.
 *  2. **Upload** -- POST in flight, spinner visible. Cancel is
 *     best-effort visual-only (the server-side BackgroundTask
 *     keeps running; the analyst can re-upload the same sha256
 *     later and the idempotent rows collide cleanly).
 *  3. **Parse** -- poll ``GET /api/v1/uploads/{uuid}`` every 2s,
 *     hard cap 15 attempts (~30s budget). Reveals drill-down
 *     link to ``/fights/{fight_id}`` on ``status="completed"``,
 *     or ``error_message`` + retry-on ``status="failed"``, or
 *     a "still parsing -- refresh in a moment" lockup on
 *     timeout.
 *
 * Why client-only
 * ===============
 * The wizard must drive interactive state transitions (file
 * selection -> POST -> poll loop -> drill-down reveal) that cannot
 * run on the server; the Server Component layer would require
 * either redirecting through 3 separate pages (URL-state machine)
 * or running the whole flow as a streaming render. A 1-page
 * Client Component is the right granularity.
 *
 * Why useReducer
 * ==============
 * The 4-step flow has explicit forbidden transitions
 * (Pick -> Parse is forbidden, Upload -> Done is forbidden, etc.).
 * A ``useState`` triplet of ``(step, file, envelope)`` invites
 * incoherent combinations (e.g. ``step="parse"`` but
 * ``envelope === null``). ``useReducer`` with a discriminated
 * union narrows the legal states to one-of-N and makes each
 * transition a named action.
 */

"use client";

import Link from "next/link";
import { useEffect, useReducer, useRef } from "react";

import {
  fetchUploadStatus,
  formatApiError,
  uploadLog,
  type UploadCreatedRow,
  type UploadStatusRow,
} from "@/lib/api";
import { formatBytes } from "@/lib/format";

import styles from "./page.module.css";

const ACCEPTED_EXT = ".zevtc";

// v0.10.25: mirror the API's compressed-upload cap so the UI can
// reject oversized files before spending bandwidth. Keep this in
// sync with the backend ``MAX_UPLOAD_SIZE_BYTES`` setting.
const MAX_UPLOAD_SIZE_BYTES = 100 * 1024 * 1024;

// Wizard parameters -- tuned so the worst-case analyst never waits
// more than ``POLL_INTERVAL_MS * POLL_MAX_ATTEMPTS`` = 2s * 15 =
// 30s without a redirect-or-reset affordance.
const POLL_INTERVAL_MS = 2_000;
const POLL_MAX_ATTEMPTS = 15;

// 2026-07-16 mobile+a11y audit U3: stable id for the file
//   rejection error paragraph so the file input can point
//   to it via ``aria-describedby`` (a screen reader will
//   announce the rejection reason immediately when the
//   input is focused). The id is module-scoped (not derived
//   from React state) so the ``aria-describedby`` attribute
//   can be a string literal — a dynamic ref would require
//   the consuming input to get the ref via React, which the
//   hidden file <input> pattern (positioned absolute + clip
//   + 1px size) doesn't support cleanly.
const REJECTED_ERROR_ID = "upload-rejected-error";

// Discriminated union for the wizard state. Each variant narrows
// which fields are available: Pick has no envelope, Upload has a
// file, Parse has an envelope, Done has a status. The compiler
// refuses incoherent combinations (e.g. ``envelope`` referenced
// while ``step !== "parse"``).
type WizardState =
  | { step: "pick"; file: File | null; rejected: string | null }
  | {
      step: "upload";
      file: File;
      error: string | null;
    }
  | {
      step: "parse";
      envelope: UploadCreatedRow;
      status: UploadStatusRow | null;
      pollError: string | null;
      timedOut: boolean;
      attempts: number;
    }
  | {
      step: "done";
      status: UploadStatusRow;
    };

type WizardAction =
  | { type: "select"; file: File | null }
  | { type: "next-from-pick"; file: File }
  | { type: "back-to-pick" }
  | { type: "upload-error"; message: string }
  | { type: "upload-success"; envelope: UploadCreatedRow }
  | { type: "poll-success"; status: UploadStatusRow }
  | { type: "poll-resolved"; status: UploadStatusRow }
  | { type: "poll-failure"; message: string }
  | { type: "poll-tick"; attempts: number }
  | { type: "poll-timeout" }
  | { type: "reset" };

const INITIAL_STATE: WizardState = {
  step: "pick",
  file: null,
  rejected: null,
};

function reducer(state: WizardState, action: WizardAction): WizardState {
  switch (action.type) {
    case "select":
      // Pick-only: only meaningful while step === "pick". The
      // ``WizardAction`` type forbids the other branches from
      // dispatching ``select`` because the legal action vocabulary
      // is enforced at every call site.
      if (state.step !== "pick") {
        return state;
      }
      if (action.file === null) {
        return { ...state, file: null, rejected: null };
      }
      if (!action.file.name.toLowerCase().endsWith(ACCEPTED_EXT)) {
        return {
          ...state,
          file: null,
          rejected: `Only ${ACCEPTED_EXT} files are accepted.`,
        };
      }
      if (action.file.size > MAX_UPLOAD_SIZE_BYTES) {
        return {
          ...state,
          file: null,
          rejected: `File is too large (${formatBytes(
            action.file.size,
          )}). Maximum is ${formatBytes(MAX_UPLOAD_SIZE_BYTES)}.`,
        };
      }
      return {
        ...state,
        file: action.file,
        rejected: null,
      };
    case "next-from-pick":
      if (state.step !== "pick") {
        return state;
      }
      return { step: "upload", file: action.file, error: null };
    case "back-to-pick":
      // Defence-in-depth reset: returns to the initial state with
      // the file cleared so the native <input type="file"> gets a
      // fresh change event on the next drop.
      return { ...INITIAL_STATE };
    case "upload-error":
      if (state.step !== "upload") {
        return state;
      }
      return { ...state, error: action.message };
    case "upload-success":
      if (state.step !== "upload") {
        return state;
      }
      return {
        step: "parse",
        envelope: action.envelope,
        status: null,
        pollError: null,
        timedOut: false,
        attempts: 0,
      };
    case "poll-success":
      if (state.step !== "parse") {
        return state;
      }
      return { ...state, status: action.status, attempts: state.attempts + 1 };
    case "poll-resolved":
      // Terminal poll outcome: ``status.status`` is one of
      // ``"completed"`` or ``"failed"`` and the wizard renders the
      // ``done`` step instead of the parse spinner.
      return { step: "done", status: action.status };
    case "poll-failure":
      if (state.step !== "parse") {
        return state;
      }
      return {
        ...state,
        pollError: action.message,
        attempts: state.attempts + 1,
      };
    case "poll-tick":
      if (state.step !== "parse") {
        return state;
      }
      return { ...state, attempts: action.attempts };
    case "poll-timeout":
      if (state.step !== "parse") {
        return state;
      }
      return { ...state, timedOut: true };
    case "reset":
      return { ...INITIAL_STATE };
  }
}

export default function UploadPage() {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);

  // Immutable ref to the upload POST result so the polling useEffect
  // closure can read the envelope without re-running on every
  // status-update state change. Re-creating the effect on every
  // tick would abort every poll as soon as the first ``poll-success``
  // dispatched, so the effect closure depends only on
  // ``state.step === "parse"`` + the envelope id (stable across
  // ticks).
  const envelopeIdRef = useRef<string | null>(null);
  const envelopeId = state.step === "parse" ? state.envelope.id : null;
  useEffect(() => {
    envelopeIdRef.current = envelopeId;
  }, [envelopeId]);

  // POST effect -- fires once on every transition into step="upload".
  // The reducer holds the ``error`` field; this effect translates
  // the awaited promise into either upload-success or upload-error.
  const uploadFile = state.step === "upload" ? state.file : null;
  useEffect(() => {
    if (uploadFile === null) {
      return;
    }
    const file = uploadFile;
    let cancelled = false;
    (async () => {
      try {
        const envelope = await uploadLog(file);
        if (cancelled) {
          return;
        }
        dispatch({ type: "upload-success", envelope });
      } catch (err) {
        if (cancelled) {
          return;
        }
        dispatch({ type: "upload-error", message: formatApiError(err) });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [uploadFile]);

  // Poll effect -- fires on every transition into step="parse".
  // Cleanup aborts the in-flight interval + the cancellation flag
  // guards the awaiting fetch against a stale resolution. The
  // ``attempts`` counter is owned by the reducer so the UI can
  // render a countdown without a second timer.
  useEffect(() => {
    if (state.step !== "parse") {
      return;
    }
    const uploadId = envelopeIdRef.current;
    if (uploadId === null) {
      // Defensive: should never happen because the upload-success
      // action sets the envelope id BEFORE the parse transition.
      // Treat as a poll-failure so the wizard degrades to the
      // timeout banner instead of an infinite spinner.
      dispatch({ type: "poll-failure", message: "internal: missing id" });
      return;
    }
    let cancelled = false;
    let attempt = 0;
    const tick = async () => {
      attempt += 1;
      dispatch({ type: "poll-tick", attempts: attempt });
      if (cancelled) {
        return;
      }
      try {
        const status = await fetchUploadStatus(uploadId);
        if (cancelled) {
          return;
        }
        if (status.status === "completed" || status.status === "failed") {
          dispatch({ type: "poll-resolved", status });
          return;
        }
        dispatch({ type: "poll-success", status });
      } catch (err) {
        if (cancelled) {
          return;
        }
        dispatch({ type: "poll-failure", message: formatApiError(err) });
      }
      if (attempt >= POLL_MAX_ATTEMPTS) {
        if (cancelled) {
          return;
        }
        dispatch({ type: "poll-timeout" });
        return;
      }
      if (cancelled) {
        return;
      }
      timerId = window.setTimeout(tick, POLL_INTERVAL_MS);
    };
    void tick();
    let timerId: number | null = null;
    return () => {
      cancelled = true;
      if (timerId !== null) {
        window.clearTimeout(timerId);
      }
    };
  }, [state.step]);

  // 2026-07-16 mobile+a11y audit U2: ref-target for the
  //   step-transition focus effect below. ``HTMLElement``
  //   (not ``HTMLDivElement``) because the ref attaches to
  //   a <main> — React's type system rejects
  //   ``HTMLDivElement`` on <main>. ``tabIndex={-1}`` makes
  //   <main> programmatically focusable without pulling
  //   it into the natural tab order (a11y best practice for
  //   focus-target divs).
  const panelRef = useRef<HTMLElement>(null);
  // Reviewer followup: skip the focus call on the FIRST
  //   render so an analyst navigating to /upload via a
  //   re-load doesn't have focus yanked to the top of the
  //   page (they may have scrolled mid-task). The guard
  //   ref flips to ``true`` after the first effect tick
  //   so post-mount step transitions behave normally.
  const hasMountedRef = useRef(false);
  useEffect(() => {
    if (!hasMountedRef.current) {
      hasMountedRef.current = true;
      return;
    }
    panelRef.current?.focus();
  }, [state.step]);

  return (
    /* 2026-07-16 mobile+a11y audit U2: ref target for the
       step-transition focus effect above. ``tabIndex={-1}``
       makes the <main> programmatically focusable without
       pulling it into the natural tab order (a11y best
       practice for non-interactive focus targets). The
       ``outline: 'none'`` style preserves visual identity
       after focus so the outline indicator doesn't appear
       over the page title text. */
    <main
      ref={panelRef}
      tabIndex={-1}
      className={styles.main}
      style={{ outline: "none" }}
    >
      <header className={styles.header}>
        <span className={styles.brand}>Combat log</span>
        <h1 className={styles.title}>Upload a .zevtc replay</h1>
        <p className={styles.lede}>
          Sends the file as <code>multipart/form-data</code> to{" "}
          <code>/api/v1/uploads</code>. The wizard surfaces the
          gateway's background parse so you can drill into the
          encounter the moment it's ready.
        </p>
      </header>

      <StepIndicator current={state.step} />

      {state.step === "pick" ? (
        <PickStep
          file={state.file}
          rejected={state.rejected}
          onSelect={(file) => dispatch({ type: "select", file })}
          onNext={(file) => dispatch({ type: "next-from-pick", file })}
        />
      ) : null}

      {state.step === "upload" ? (
        <UploadStep
          file={state.file}
          error={state.error}
          onCancel={() => dispatch({ type: "back-to-pick" })}
        />
      ) : null}

      {state.step === "parse" ? (
        <ParseStep
          envelope={state.envelope}
          status={state.status}
          pollError={state.pollError}
          timedOut={state.timedOut}
          attempts={state.attempts}
          onRetry={() => dispatch({ type: "back-to-pick" })}
          onWait={() => dispatch({ type: "poll-timeout" })}
        />
      ) : null}

      {state.step === "done" ? (
        <DoneStep
          status={state.status}
          onReset={() => dispatch({ type: "reset" })}
        />
      ) : null}
    </main>
  );
}

/**
 * 3-segment horizontal step indicator with an aria-current marker
 * on the active segment. ``current`` is the narrowest possible
 * type the wizard exposes (``WizardState["step"]``) so the
 * indicator drops segments automatically when state machine
 * additions land.
 */
function StepIndicator({
  current,
}: {
  current: WizardState["step"];
}) {
  const steps: { id: WizardState["step"]; label: string }[] = [
    { id: "pick", label: "Pick file" },
    { id: "upload", label: "Upload" },
    { id: "parse", label: "Parse" },
  ];
  // The "done" step is a terminal state -- render an extra
  // celebration segment to acknowledge the success.
  const indices = { pick: 0, upload: 1, parse: 2, done: 3 } as const;
  const activeIndex = indices[current];
  return (
    <ol
      className={styles.stepIndicator}
      aria-label="Upload wizard progress"
    >
      {steps.map((step, idx) => (
        <li
          key={step.id}
          className={
            idx === activeIndex
              ? styles.stepActive
              : idx < activeIndex
                ? styles.stepDone
                : styles.stepPending
          }
          aria-current={idx === activeIndex ? "step" : undefined}
          data-testid={`step-indicator-${step.id}`}
        >
          <span className={styles.stepNumber}>{idx + 1}</span>
          <span className={styles.stepLabel}>{step.label}</span>
        </li>
      ))}
      {current === "done" ? (
        <li
          className={styles.stepActive}
          aria-current="step"
          data-testid="step-indicator-done"
        >
          <span className={styles.stepNumber}>4</span>
          <span className={styles.stepLabel}>Done</span>
        </li>
      ) : null}
    </ol>
  );
}

function PickStep({
  file,
  rejected,
  onSelect,
  onNext,
}: {
  file: File | null;
  rejected: string | null;
  onSelect: (file: File | null) => void;
  onNext: (file: File) => void;
}) {
  const canAdvance = file !== null && rejected === null;
  return (
    <section
      className={styles.panel}
      aria-label="Step 1: choose a file"
      data-testid="step-pick"
    >
      <label className={styles.fileLabel}>
        <span className={styles.fileLabelText}>Combat log file</span>
        <input
          type="file"
          accept={ACCEPTED_EXT}
          onChange={(event) =>
            onSelect(event.currentTarget.files?.[0] ?? null)
          }
          className={styles.fileInput}
          data-testid="file-input"
          /* 2026-07-16 mobile+a11y audit U3: link the
             hidden file <input> to the rejected-error
             <p> via ``aria-describedby`` so a screen
             reader announces the rejection reason
             ("Only .zevtc files ..." / "File is too large
             ..." / ...) immediately when the input is
             focused. The id is stable across renders
             (REJECTED_ERROR_ID is module-scoped), so
             aria-describedby can be a plain string. SR
             tolerates a missing-or-empty referenced id
             (silently no-ops), so the attribute is safe
             even when ``rejected === null``. */
          aria-describedby={REJECTED_ERROR_ID}
        />
        <span className={styles.fileChip} data-testid="file-chip">
          {file === null
            ? `No file selected — click to choose a ${ACCEPTED_EXT} (max ${formatBytes(
                MAX_UPLOAD_SIZE_BYTES,
              )})`
            : `${file.name} · ${formatBytes(file.size)}`}
        </span>
      </label>        {rejected !== null ? (
          <p
            id={REJECTED_ERROR_ID}
            className={styles.error}
            role="alert"
            data-testid="rejected"
          >
            {rejected}
          </p>
        ) : null}

      <div className={styles.buttonRow}>
        <button
          type="button"
          disabled={!canAdvance}
          className={styles.submit}
          onClick={() => {
            if (file !== null) {
              onNext(file);
            }
          }}
          data-testid="next"
        >
          Next
        </button>
      </div>
    </section>
  );
}

function UploadStep({
  file,
  error,
  onCancel,
}: {
  file: File;
  error: string | null;
  onCancel: () => void;
}) {
  return (
    <section
      className={styles.panel}
      aria-label="Step 2: upload in progress"
      aria-live="polite"
      data-testid="step-upload"
    >
      <div className={styles.spinnerRow}>
        <span
          className={styles.spinner}
          aria-hidden="true"
          data-testid="spinner"
        />
        <div>
          <p className={styles.fileLabelText}>Uploading…</p>
          <p className={styles.fileChipStatic}>
            {file.name} · {formatBytes(file.size)}
          </p>
        </div>
      </div>
      {error !== null ? (
        <p className={styles.error} role="alert" data-testid="error">
          {error}
        </p>
      ) : null}
      <div className={styles.buttonRow}>
        <button
          type="button"
          className={styles.muted}
          disabled={error !== null}
          onClick={onCancel}
          data-testid="cancel"
        >
          Cancel
        </button>
      </div>
    </section>
  );
}

function ParseStep({
  envelope,
  status,
  pollError,
  timedOut,
  attempts,
  onRetry,
  onWait,
}: {
  envelope: UploadCreatedRow;
  status: UploadStatusRow | null;
  pollError: string | null;
  timedOut: boolean;
  attempts: number;
  onRetry: () => void;
  onWait: () => void;
}) {
  return (
    <section
      className={styles.panel}
      aria-label="Step 3: parsing in progress"
      aria-live="polite"
      data-testid="step-parse"
    >
      <dl className={styles.cardGrid}>
        <dt>ID</dt>
        <dd className={styles.mono}>{envelope.id}</dd>
        <dt>SHA-256</dt>
        <dd className={styles.mono}>
          {envelope.sha256.slice(0, 8)}…{envelope.sha256.slice(-4)}
        </dd>
        <dt>Status</dt>
        <dd>
          <span
            className={styles.badge}
            data-testid="parse-status"
          >
            {status?.status ?? "pending"}
          </span>
          <span className={styles.faint}>
            {" "}
            · attempt {attempts}/{POLL_MAX_ATTEMPTS}
          </span>
        </dd>
      </dl>
      {pollError !== null ? (
        <p className={styles.error} role="alert" data-testid="poll-error">
          {pollError}
        </p>
      ) : null}
      {timedOut ? (
        <p className={styles.warn} role="status" data-testid="poll-timeout">
          Still parsing after {POLL_MAX_ATTEMPTS * (POLL_INTERVAL_MS / 1000)}s.
          Refresh in a moment, or retry.
        </p>
      ) : null}
      <div className={styles.buttonRow}>
        <button
          type="button"
          className={styles.muted}
          onClick={onRetry}
          data-testid="retry"
        >
          Start over
        </button>
        {timedOut ? (
          <button
            type="button"
            className={styles.submit}
            onClick={onWait}
            data-testid="force-done"
          >
            Mark as wedged
          </button>
        ) : null}
      </div>
    </section>
  );
}

function DoneStep({
  status,
  onReset,
}: {
  status: UploadStatusRow;
  onReset: () => void;
}) {
  const drilldownHref =
    status.fight_id !== null ? `/fights/${status.fight_id}` : "/fights";
  return (
    <section
      className={styles.panel}
      aria-label="Upload complete"
      aria-live="polite"
      data-testid="step-done"
    >
      <h2 className={styles.cardTitle}>Upload complete</h2>
      <dl className={styles.cardGrid}>
        <dt>ID</dt>
        <dd className={styles.mono}>{status.id}</dd>
        <dt>SHA-256</dt>
        <dd className={styles.mono}>
          {status.sha256.slice(0, 8)}…{status.sha256.slice(-4)}
        </dd>
        <dt>Status</dt>
        <dd>
          <span className={styles.badge}>{status.status}</span>
        </dd>
      </dl>
      <p className={styles.cardFooter}>
        {status.fight_id !== null
          ? "Open the parsed encounter now:"
          : "The fight id is missing on the response -- open the fights list to drill in."}{" "}
        <Link href={drilldownHref} className={styles.cardLink}>
          {status.fight_id !== null
            ? `/fights/${status.fight_id}`
            : "/fights"}
        </Link>
      </p>
      <div className={styles.buttonRow}>
        <button
          type="button"
          className={styles.submit}
          onClick={onReset}
          data-testid="upload-another"
        >
          Upload another
        </button>
      </div>
    </section>
  );
}


