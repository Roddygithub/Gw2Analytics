"use client";

/**
 * Small Client Component for the global player search bar.
 *
 * Lives in the root layout's header bar (above every page) so
 * the analyst can pivot to a player profile from anywhere on
 * the site without first navigating to ``/players``. The submit
 * handler does a client-side ``router.push`` to
 * ``/players/${encodeURIComponent(raw.trim())}`` so the
 * gateway's ``:path`` converter receives the URL-encoded form
 * (the route accepts ``/``-bearing account names; the input
 * itself accepts any trimmed string).
 *
 * v0.10.28 plan 163 migration: dropped the React.CSSProperties
 * inline-style objects (FORM_STYLE / INPUT_STYLE / BUTTON_STYLE /
 * LABEL_STYLE imports from ``@/shared/styles``) in favour of
 * a CSS module. Root cause of the prior SSR/CSR hydration
 * mismatch was React's inline-style renderer expanding CSS
 * shorthand properties (e.g. ``border: '1px solid var(--border)'``)
 * into longhand properties (``borderWidth`` + ``borderStyle``
 * + ``borderColor``) on the client DOM while the server-rendered
 * HTML kept the shorthand -- React's hydration reconciliation
 * then saw the mismatch and logged a hydration warning.
 * CSS modules are server-rendered as plain class-name selectors;
 * the styles are applied via the stylesheet (no inline-style
 * expansion), so SSR and CSR render identically.
 *
 * The disabled-state styling for the search button is now
 * handled via the native ``:disabled`` pseudo-class in the
 * CSS module (no inline ``cursor: not-allowed`` or
 * ``opacity: 0.5`` overrides needed at the JSX level).
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
import React from "react";

import { useState } from "react";
import { useRouter } from "next/navigation";

import styles from "./PlayerSearchBar.module.css";

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
      data-testid="player-search-form"
      className={styles.form}
    >
      <label htmlFor="player-search" className={styles.label}>
        Player
      </label>
      <input
        id="player-search"
        name="account_name"
        type="search"
        placeholder=":account.1234"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        className={styles.input}
      />
      <button type="submit" disabled={!value.trim()} className={styles.button}>
        Search
      </button>
    </form>
  );
}
