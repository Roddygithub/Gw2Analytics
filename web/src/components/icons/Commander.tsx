"use client";

/**
 * F17 W.1 — Commander Crown glyph.
 *
 * Why inline SVG (not a PNG icon):
 * - The crown is a single-cell chrome element; an inline SVG keeps
 *   the asset deterministic (no network fetch, no PNG in the
 *   `icons/` bundle, no Acquisition drift).
 * - Inline SVG renders crisp at any size (16-48px) and inherits the
 *   app's `--accent` token for hover/focus states via CSS.
 * - Total cost: ~250 bytes per render (path data + rect + circle).
 *
 * Visual design
 * =============
 * Three peaks (left + center + right) + horizontal band + small
 * circular handle atop the center peak. Color palette: gold
 * (`#f5b800` peak, `#b58900` band) with a `#7c5e10` outline. The
 * glyph mirrors the arcdps / Elite Insights commander marker.
 *
 * A11y: role="img" + aria-label="Commandeur" so screen readers
 * announce the role consistently; the rendered title="Commandeur"
 * attribute augments tooltip-style tool consumers (e.g. AG Grid's
 * native browser tooltip on hover, which still works under
 * virtualization).
 */

import React from "react";

interface CommanderCrownProps {
  size?: number;
}

export function CommanderCrown({ size = 18 }: CommanderCrownProps) {
  return (
    <span
      data-testid="commander-crown"
      title="Commandeur"
      style={{
        display: "inline-flex",
        alignItems: "center",
        verticalAlign: "middle",
      }}
    >
      <svg
        width={size}
        height={size}
        viewBox="0 0 24 24"
        role="img"
        aria-label="Commandeur"
      >
        {/* Three-peak crown body */}
        <path
          d="M3 16 L5 8 L9 12 L12 5 L15 12 L19 8 L21 16 Z"
          fill="#f5b800"
          stroke="#7c5e10"
          strokeWidth="1"
          strokeLinejoin="round"
        />
        {/* Horizontal base band */}
        <rect x="3" y="16" width="18" height="3" fill="#b58900" />
        {/* Center handle / jewel */}
        <circle cx="12" cy="4.5" r="1.5" fill="#fff5cc" />
        {/* Side studs */}
        <circle cx="5" cy="8" r="0.8" fill="#fff5cc" />
        <circle cx="19" cy="8" r="0.8" fill="#fff5cc" />
      </svg>
    </span>
  );
}
