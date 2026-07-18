/**
 * SectionErrorChip — per-section error indicator (plan 169 commit #1).
 *
 * Consolidates the inline ``<p data-testid="X-error" style={accent}>``
 * shape that was duplicated across 5+ per-section error blocks on
 * :file:`web/src/app/fights/[id]/page.tsx`. The earlier inline
 * pattern had inconsistent testid naming (``{ section }-error``)
 * and inconsistent accent-style application; this chip provides
 * a single declarative API + a single testid convention.
 *
 * Why a Server Component
 * ======================
 * The chip renders a static ``<p>`` with a text message and a
 * testid. There is no browser-only API required (``useEffect``,
 * ``useRouter``, ``useState`` -- none). A Server Component is the
 * smallest layer that satisfies the contract; matching the page's
 * own Server-Component layer (the page is NOT a Client Component).
 *
 * Why ``role="alert"``
 * ====================
 * The page-level error boundary (`web/src/app/fights/[id]/error.tsx`)
 * renders an actionable alert with a "Try again" button. The
 * per-section chip is non-actionable -- when this section fails,
 * the analyst navigates elsewhere or refreshes the whole page --
 * so ``role="alert"`` (which announces immediately to screen
 * readers) is the right semantic per WAI-ARIA. We do NOT use
 * ``role="alertdialog"`` because there is no confirmation dialog.
 *
 * Why no retry button
 * ===================
 * The page-level error.tsx has a "Try again" button because it
 * belongs to the React error-boundary contract (``reset``
 * callback). A per-section retry would require extracting the
 * section into its own fetch-owning subcomponent (plan 169
 * commits #3 + #4 ship that decomposition). For the v0.10.26-pre
 * chip, the lazy retry is "navigate back to /fights and back" --
 * acceptable UX for a non-critical section failure.
 *
 * Props
 * =====
 * - ``testid`` (required): the ``data-testid`` attribute. Callers
 *   conventionally use ``"{section-name}-section-error"`` so the
 *   testid clearly distinguishes the chip from the page-level
 *   ``"fight-error-panel"``.
 * - ``message`` (required): the human-readable error message
 *   (typically the upstream ``formatApiError(...)`` output +
 *   a section-specific prefix like ``"Failed to load squads: "``).
 *
 * Companion
 * =========
 * The pilot test at
 * :file:`web/tests/components/section-error-chip.test.tsx` verifies
 * the chip renders the testid + the message verbatim. Page-level
 * integration tests live in
 * :file:`web/tests/app/fight-events-page.test.tsx` (the chip is
 * passed as a delegate).
 */
export interface SectionErrorChipProps {
  testid: string;
  message: string;
}

const CHIP_STYLE: React.CSSProperties = {
  color: "var(--accent)",
  fontSize: 14,
  margin: 0,
  fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
};

export function SectionErrorChip({
  testid,
  message,
}: SectionErrorChipProps) {
  return (
    <p role="alert" data-testid={testid} style={CHIP_STYLE}>
      {message}
    </p>
  );
}
