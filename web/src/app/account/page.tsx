/**
 * Client Component that collects a GW2 API key and posts it to the
 * gateway's ``/api/v1/account`` Bearer-protected endpoint to resolve
 * the user's current world triple.
 *
 * Why form is client-side
 * =======================
 * The key is held in React state, sent over HTTPS to the gateway,
 * and never persisted in localStorage / cookies by this component
 * (Next.js developer should add a server-side proxy if production
 * wants to bypass browser exposure entirely -- the gateway is the
 * source of truth either way).
 */

"use client";

import { useState } from "react";

import { formatApiError, resolveAccount, type AccountEnrichedRow } from "@/lib/api";

export default function AccountPage() {
  const [apiKey, setApiKey] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<AccountEnrichedRow | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!apiKey.trim()) {
      return;
    }
    setSubmitting(true);
    setError(null);
    setResult(null);
    try {
      const resolved = await resolveAccount(apiKey);
      setResult(resolved);
      // Clear the key from component state once consumed: keeps the
      // browser DevTools surface small if the tab is left open and
      // signals to the user that the form is "spent".
      setApiKey("");
    } catch (err) {
      // Same canonical formatter as /upload -- see formatApiError.
      setError(formatApiError(err));
    } finally {
      setSubmitting(false);
    }
  }

  const disabled = submitting || !apiKey.trim();

  return (
    <main style={{ padding: "32px", maxWidth: 560 }}>
      <h1 style={{ fontSize: 28, marginBottom: 8 }}>
        Resolve GW2 API key
      </h1>
      <p style={{ opacity: 0.7, marginBottom: 24 }}>
        Posts your key as <code>Bearer</code> to{" "}
        <code>/api/v1/account</code>. The key is not stored.
      </p>

      <form
        onSubmit={handleSubmit}
        style={{ display: "flex", flexDirection: "column", gap: 12 }}
      >
        <input
          type="password"
          value={apiKey}
          onChange={(event) => setApiKey(event.target.value)}
          placeholder="GW2 API key"
          autoComplete="off"
          required
          minLength={1}
          style={{
            padding: "10px 12px",
            borderRadius: 8,
            border: "1px solid var(--border)",
            background: "var(--surface)",
            color: "var(--foreground)",
            fontFamily: "var(--font-geist-mono)",
          }}
        />
        <button
          type="submit"
          disabled={disabled}
          style={{
            padding: "10px 16px",
            borderRadius: 8,
            border: "1px solid var(--accent)",
            background: "transparent",
            color: "var(--accent)",
            cursor: disabled ? "not-allowed" : "pointer",
            opacity: disabled ? 0.5 : 1,
          }}
        >
          {submitting ? "Resolving…" : "Resolve"}
        </button>
      </form>

      {result ? (
        <section
          style={{
            marginTop: 24,
            padding: 16,
            borderRadius: 12,
            background: "var(--surface)",
            border: "1px solid var(--border)",
          }}
        >
          <h2 style={{ fontSize: 16, marginBottom: 12 }}>Resolved world</h2>
          <dl
            style={{
              display: "grid",
              gridTemplateColumns: "auto 1fr",
              gap: "4px 16px",
            }}
          >
            <dt>World ID</dt>
            <dd style={{ fontFamily: "var(--font-geist-mono)" }}>
              {result.world_id}
            </dd>
            <dt>Name</dt>
            <dd>{result.world_name}</dd>
            <dt>Population</dt>
            <dd>{result.world_population}</dd>
          </dl>
        </section>
      ) : null}

      {error ? (
        <p style={{ marginTop: 16, color: "#ff6e6e" }}>Error: {error}</p>
      ) : null}
    </main>
  );
}
