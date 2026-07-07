"use client";

/**
 * Small Client Component for the global player search bar.
 *
 * Lives in the root layout's header bar (above every page) so
 * the analyst can pivot to a player profile from anywhere on the
 * site without first navigating to ``/players``. The submit
 * handler does a client-side ``router.push`` to
 * ``/players/${encodeURIComponent(raw.trim())}`` so the
 * gateway's ``:path`` converter receives the URL-encoded form
 * (the route accepts ``/``-bearing account names; the input
 * itself accepts any trimmed string).
 *
 * Why a global header bar (vs a /players-scoped search only)
 * ==========================================================
 * The canonical "search by account name" affordance should be
 * available on every page, not just the players list. The
 * header bar is the Next.js-conventional location; the
 * ``/players`` list page does NOT add a second search input
 * (would duplicate the affordance + force the user to think
 * about which input is the "right" one).
 *
 * Why router.push (not router.replace)
 * ====================================
 * The back button should carry the analyst through the search
 * history. ``router.push`` is the canonical choice for a
 * search-bar submit; ``router.replace`` would silently rewrite
 * the current entry and break the back button.
 *
 * Why a ``<form onSubmit>`` (not a click handler on a button)
 * ===========================================================
 * The Enter key naturally submits the form (standard browser
 * behaviour) and the submit event gives us a single
 * uniform handler for both Enter and the "Search" button.
 * ``event.preventDefault()`` stops the default GET-form
 * navigation; the client-side ``router.push`` carries the
 * analyst to the player page.
 */

import { useState } from "react";
import { useRouter } from "next/navigation";

export function PlayerSearchBar() {
  const router = useRouter();
  const [value, setValue] = useState("");

  const onSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const trimmed = value.trim();
    if (!trimmed) return;
    router.push(`/players/${encodeURIComponent(trimmed)}`);
  };

  return (
    <form
      onSubmit={onSubmit}
      role="search"
      style={{ display: "flex", gap: 8, alignItems: "center" }}
    >
      <label
        htmlFor="player-search"
        style={{
          fontSize: 12,
          color: "var(--foreground)",
          opacity: 0.7,
        }}
      >
        Player
      </label>
      <input
        id="player-search"
        name="account_name"
        type="search"
        placeholder=":account.1234"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        style={{
          padding: "4px 8px",
          fontSize: 13,
          fontFamily: "var(--font-geist-mono), ui-monospace, monospace",
          background: "var(--background)",
          color: "var(--foreground)",
          border: "1px solid var(--border)",
          borderRadius: 4,
          minWidth: 200,
        }}
      />
      <button
        type="submit"
        disabled={!value.trim()}
        style={{
          padding: "4px 12px",
          fontSize: 13,
          background: "var(--accent)",
          color: "var(--background)",
          border: "none",
          borderRadius: 4,
          cursor: value.trim() ? "pointer" : "not-allowed",
          opacity: value.trim() ? 1 : 0.5,
        }}
      >
        Search
      </button>
    </form>
  );
}
