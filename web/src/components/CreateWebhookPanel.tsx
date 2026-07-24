/**
 * CreateWebhookPanel -- Client Component that drives a 3-phase
 * state machine for registering a new webhook subscription:
 *
 *   1. ``closed`` -- only the ``New subscription`` trigger
 *      button is visible. Keeps the subscriptions table compact
 *      for operators who are just here to inspect / revoke /
 *      replay.
 *   2. ``form`` -- URL (required) + description (optional) +
 *      filter (optional JSON object, advanced). Submit
 *      transitions to either ``reveal`` (on 201) OR renders an
 *      inline error card (on 4xx -- typically the
 *      `_validate_webhook_url` SSRF guard returning 422).
 *   3. ``reveal`` -- the one-shot plaintext ``secret`` callout
 *      with a Copy-to-clipboard button + a mandatory
 *      ``I have securely stored this secret.`` acknowledgement
 *      checkbox. The ``Done`` button is disabled until the
 *      checkbox is checked. Closing the panel triggers
 *      ``router.refresh()`` so the new subscription surfaces in
 *      the WebhookSubscriptionsGrid table.
 *
 * Why a 3-phase state machine (not a single form with the
 * secret revealed inline)
 * ============================================================
 * The backend returns the plaintext secret ONCE on the 201
 * response (Fernet envelope encryption-at-rest for every later
 * fetch). If the form simply closed after a successful POST,
 * the secret would be silently lost and the operator would
 * have to re-register. The forced acknowledgement flow mirrors
 * industry standards (Stripe, GitHub webhooks, Slack apps) so
 * the analyst is forced to interact with the secret value
 * BEFORE it disappears, not after.
 *
 * Why a single Client Component (not a multi-page wizard)
 * ==========================================================
 * The whole flow is short (< 30 s typical) and has zero
 * cross-page state. A multi-page wizard would require
 * server-side storage of the in-flight secret (because the
 * one-shot contract means the secret does NOT survive a
 * refresh). The 3-phase Client Component flow keeps the
 * plaintext secret in React state for the lifetime of the
 * wizard and only crosses the network once.
 *
 * Why useReducer + discriminated union
 * -------------------------------------
 * The 3 phases have explicit forbidden transitions (cannot
 * submit from `reveal`, cannot edit from `closed`, etc.).
 * 3 separate `useState`s would invite incoherent
 * combinations (e.g. `mode === "reveal"` but
 * `revealedSecret === null`). The discriminated union
 * narrows the legal states to one-of-N and makes each
 * transition a named action.
 */

"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useReducer, useRef } from "react";

import {
  createWebhook,
  DEFAULT_WEBHOOK_FILTER,
  formatApiError,
  type CreateWebhookPayload,
  type WebhookSubscriptionCreatedRow,
} from "@/lib/api";

import styles from "./CreateWebhookPanel.module.css";

type Phase = "closed" | "form" | "reveal";

type State =
  | { phase: "closed" }
  | {
      phase: "form";
      url: string;
      description: string;
      filter: string;
      submitting: boolean;
      error: string | null;
    }
  | {
      phase: "reveal";
      created: WebhookSubscriptionCreatedRow;
      acknowledged: boolean;
      copied: boolean;
    };

type Action =
  | { type: "open" }
  | { type: "cancel" }
  | { type: "update"; field: "url" | "description" | "filter"; value: string }
  | { type: "submit-start" }
  | { type: "submit-success"; created: WebhookSubscriptionCreatedRow }
  | { type: "submit-failure"; message: string }
  | { type: "acknowledge"; value: boolean }
  | { type: "copied" }
  | { type: "done" };

const INITIAL_STATE: State = { phase: "closed" };

function emptyForm(): Extract<State, { phase: "form" }> {
  return {
    phase: "form",
    url: "",
    description: "",
    filter: "",
    submitting: false,
    error: null,
  };
}

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "open":
      // From any closed or revealed state, re-entering the form
      // resets every field. We do NOT reuse the prior values for
      // two reasons: (1) the operator could accidentally re-POST
      // the same URL twice; (2) starting fresh matches the
      // expect-after-error flow (the analyst fixes the URL and
      // re-submits -- starting from a stale URL adds confusion).
      return emptyForm();
    case "cancel":
      return { phase: "closed" };
    case "update":
      if (state.phase !== "form") {
        return state;
      }
      return { ...state, [action.field]: action.value, error: null };
    case "submit-start":
      if (state.phase !== "form") {
        return state;
      }
      return { ...state, submitting: true, error: null };
    case "submit-success":
      // Symmetric with submit-start / submit-failure: only
      // transitions from `form`. Guards against the dispatcher
      // ever firing this from a non-form phase (e.g. an
      // accidental post from the reveal panel's async code).
      if (state.phase !== "form") {
        return state;
      }
      return {
        phase: "reveal",
        created: action.created,
        acknowledged: false,
        copied: false,
      };
    case "submit-failure":
      if (state.phase !== "form") {
        return state;
      }
      return { ...state, submitting: false, error: action.message };
    case "acknowledge":
      if (state.phase !== "reveal") {
        return state;
      }
      return { ...state, acknowledged: action.value };
    case "copied":
      if (state.phase !== "reveal") {
        return state;
      }
      return { ...state, copied: true };
    case "done":
      if (state.phase !== "reveal") {
        return state;
      }
      return { phase: "closed" };
  }
}

export function CreateWebhookPanel() {
  const router = useRouter();
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);

  // When the panel moves INTO the `reveal` phase, focus the
  // secret callout so a keyboard-only operator can navigate the
  // acknowledge / done controls immediately. We skip the call
  // on the FIRST render so re-mounts mid-task don't yank
  // focus (parallels the `upload/page.tsx` focus effect).
  const hasMountedRef = useRef(false);
  const revealRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!hasMountedRef.current) {
      hasMountedRef.current = true;
      return;
    }
    if (state.phase === "reveal") {
      revealRef.current?.focus();
    }
  }, [state.phase]);

  const handleSubmit = useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (state.phase !== "form" || state.submitting) {
        return;
      }
      const url = state.url.trim();
      if (!url) {
        dispatch({ type: "submit-failure", message: "URL is required" });
        return;
      }
      // Parse the optional filter field as JSON. An empty /
      // whitespace string is treated as :data:\`DEFAULT_WEBHOOK_FILTER\`
      // (``{ kind: "upload_completed" }``) because the backend
      // rejects ``filter.kind``-missing subscriptions at the
      // Pydantic validator. The closed set of supported kinds
      // mirrors the dispatcher's event types -- sending
      // anything else at creation yields a subscription that
      // is never fired (the dispatcher silently skips it).
      // A parse failure surfaces as an inline error so the
      // analyst can fix the JSON before submitting; we do NOT
      // silently send malformed JSON.
      let filterPayload: Record<string, unknown> = {
        ...DEFAULT_WEBHOOK_FILTER,
      };
      const filterTrimmed = state.filter.trim();
      if (filterTrimmed !== "") {
        try {
          const parsed: unknown = JSON.parse(filterTrimmed);
          if (
            parsed === null ||
            typeof parsed !== "object" ||
            Array.isArray(parsed)
          ) {
            throw new Error("filter must be a JSON object");
          }
          filterPayload = parsed as Record<string, unknown>;
        } catch (err) {
          dispatch({
            type: "submit-failure",
            message: `filter: ${
              err instanceof Error ? err.message : String(err)
            }`,
          });
          return;
        }
      }
      dispatch({ type: "submit-start" });
      const payload: CreateWebhookPayload = {
        url,
        description:
          state.description.trim() === "" ? null : state.description,
        filter: filterPayload,
      };
      try {
        const created = await createWebhook(payload);
        dispatch({ type: "submit-success", created });
      } catch (err) {
        dispatch({ type: "submit-failure", message: formatApiError(err) });
      }
    },
    // Deps: TypeScript cannot narrow a discriminated-union
    // type at the useCallback deps-array level (the early
    // return inside the closure narrows ``state`` after the
    // guard, but the deps array is evaluated at the
    // useCallback call site where ``state`` is the whole
    // union -- ``state.url`` etc. don't statically exist on
    // the union, so a per-field deps list fails with TS2339).
    //
    // The canonical workaround is ``[state]`` -- wider than
    // ideal but safe: form-field edits always dispatch a
    // reducer action that constructs a new ``state`` object,
    // so the wider deps doesn't introduce a stale-closure
    // bug. The early-return guard inside the closure
    // (``state.phase !== "form" || state.submitting``)
    // rejects every non-form case so the body never
    // dereferences a missing field.
    [state],
  );

  const handleCopy = useCallback(async (secret: string) => {
    try {
      if (typeof navigator !== "undefined" && navigator.clipboard) {
        await navigator.clipboard.writeText(secret);
      } else {
        // Fallback for exotic browsers without the Clipboard
        // API: create a throwaway textarea, select, and use
        // the legacy `document.execCommand("copy")` shim.
        const ta = document.createElement("textarea");
        ta.value = secret;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      }
      dispatch({ type: "copied" });
    } catch {
      // Copy failure is non-fatal: the analyst can still
      // visually read the secret and copy it manually. We do
      // not surface an error card because the secret is
      // already revealed -- surfacing would only distract.
    }
  }, []);

  const handleDone = useCallback(() => {
    dispatch({ type: "done" });
    // `router.refresh()` re-runs the server component which
    // re-fetches both the subscriptions list + the DLQ (the
    // latter is unaffected, the former picks up the newly
    // registered row).
    router.refresh();
  }, [router]);

  if (state.phase === "closed") {
    return (
      <div className={styles.container}>
        <button
          type="button"
          className={styles.openButton}
          onClick={() => dispatch({ type: "open" })}
          data-testid="create-webhook-open"
        >
          + New subscription
        </button>
      </div>
    );
  }

  if (state.phase === "form") {
    const canSubmit = state.url.trim() !== "" && !state.submitting;
    return (
      <div className={styles.container} data-testid="create-webhook-form">
        <form className={styles.form} onSubmit={handleSubmit}>
          <label className={styles.field}>
            <span className={styles.labelText}>URL</span>
            <input
              type="url"
              required
              value={state.url}
              placeholder="https://example.com/webhook"
              onChange={(e) =>
                dispatch({
                  type: "update",
                  field: "url",
                  value: e.target.value,
                })
              }
              className={styles.input}
              aria-describedby="create-webhook-url-help"
              data-testid="create-webhook-url"
            />
            <span id="create-webhook-url-help" className={styles.helpText}>
              HTTPS required, or http://localhost for trusted dev
              only. Private / loopback / link-local / multicast
              addresses are rejected.
            </span>
          </label>

          <label className={styles.field}>
            <span className={styles.labelText}>Description (optional)</span>
            <input
              type="text"
              value={state.description}
              placeholder="e.g. CI smoke tests"
              onChange={(e) =>
                dispatch({
                  type: "update",
                  field: "description",
                  value: e.target.value,
                })
              }
              className={styles.input}
              data-testid="create-webhook-description"
            />
          </label>

          <label className={styles.field}>
            <span className={styles.labelText}>
              Filter (optional JSON object)
            </span>
            <textarea
              value={state.filter}
              placeholder={JSON.stringify(DEFAULT_WEBHOOK_FILTER)}
              rows={3}
              onChange={(e) =>
                dispatch({
                  type: "update",
                  field: "filter",
                  value: e.target.value,
                })
              }
              className={styles.textarea}
              data-testid="create-webhook-filter"
            />
            <span className={styles.helpText}>
              Leave empty to default to{" "}
              <code>{JSON.stringify(DEFAULT_WEBHOOK_FILTER)}</code>{" "}
              (the only currently-supported kind; the dispatcher
              rejects unknown kinds at creation so a typo
              doesn't yield a subscription that never fires).
            </span>
          </label>

          {state.error !== null ? (
            <p
              className={styles.error}
              role="alert"
              data-testid="create-webhook-error"
            >
              {state.error}
            </p>
          ) : null}

          <div className={styles.buttonRow}>
            <button
              type="submit"
              disabled={!canSubmit}
              className={styles.submit}
              data-testid="create-webhook-submit"
            >
              {state.submitting ? "Creating…" : "Create"}
            </button>
            <button
              type="button"
              className={styles.muted}
              onClick={() => dispatch({ type: "cancel" })}
              disabled={state.submitting}
            >
              Cancel
            </button>
          </div>
        </form>
      </div>
    );
  }

  // state.phase === "reveal"
  const secret = state.created.secret;
  return (
    <div
      ref={revealRef}
      tabIndex={-1}
      className={styles.reveal}
      data-testid="create-webhook-reveal"
    >
      <h3 className={styles.revealTitle}>Subscription registered</h3>
      <p className={styles.revealLede}>
        <strong>Copy the secret below now.</strong> This is the
        only time it will be shown. The plaintext is Fernet
        envelope-encrypted at rest; the ID{" "}
        <code>{state.created.id}</code> is the public handle for
        revoke / inspect.
      </p>

      <div className={styles.copyBlock}>
        <div className={styles.secretRow}>
          <code
            className={styles.secret}
            aria-label="One-shot subscription secret"
            data-testid="create-webhook-secret"
          >
            {secret}
          </code>
          <button
            type="button"
            className={styles.copyButton}
            onClick={() => handleCopy(secret)}
            data-testid="create-webhook-copy"
          >
            {state.copied ? "Copied ✓" : "Copy"}
          </button>
        </div>
        {/*
          CSS-only focus hint: the ``.copyBlock:focus-within``
          rule in the CSS module surfaces this paragraph when
          the copy button OR the secret span has focus, so
          keyboard-only users aren't left wondering how to
          read the secret. Replaces the prior ``copyFocused``
          useState that the round-1 code-review flagged as
          dead code.
        */}
        <p className={styles.copyStatusHint}>
          <kbd>Cmd</kbd> + click to copy on macOS, or select the
          text manually.
        </p>
      </div>

      {state.copied ? (
        <p className={styles.copyStatus} role="status">
          Secret added to clipboard.
        </p>
      ) : null}

      <label className={styles.ackRow}>
        <input
          type="checkbox"
          checked={state.acknowledged}
          onChange={(e) =>
            dispatch({ type: "acknowledge", value: e.target.checked })
          }
          data-testid="create-webhook-ack"
        />
        <span>I have securely stored this secret.</span>
      </label>

      <div className={styles.buttonRow}>
        <button
          type="button"
          disabled={!state.acknowledged}
          onClick={handleDone}
          className={styles.submit}
          data-testid="create-webhook-done"
        >
          Done
        </button>
      </div>
    </div>
  );
}
