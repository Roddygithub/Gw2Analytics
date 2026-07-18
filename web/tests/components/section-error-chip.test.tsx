import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { SectionErrorChip } from "@/components/SectionErrorChip";

/**
 * v0.10.26-pre plan 169 commit #1 pilot: verify the chip
 * renders the testid + the message verbatim + the role="alert"
 * attribute is set. The chip is a Server Component (no
 * "use client" directive), so the existing setup.ts vi.mock
 * layer (which mocks React components only) does NOT need a
 * new vi.mock for this file.
 *
 * v0.10.26-pre plan 169 commit #1: the chip component
 * consolidates the inline <p data-testid style={accent}> pattern
 * duplicated across 5+ per-section error blocks on
 * ``web/src/app/fights/[id]/page.tsx``. The pilot pins the
 * contract BEFORE the page.tsx refactor in commit #2 ships.
 */
describe("SectionErrorChip pilot", () => {
  it("renders the testid + the message verbatim", () => {
    render(
      <SectionErrorChip
        testid="squads-section-error"
        message="Failed to load squads: 502 Bad Gateway"
      />,
    );
    const chip = screen.getByTestId("squads-section-error");
    expect(chip).toBeInTheDocument();
    expect(chip).toHaveTextContent(
      "Failed to load squads: 502 Bad Gateway",
    );
  });

  it("has role=alert for accessibility (announces immediately to screen readers)", () => {
    render(
      <SectionErrorChip
        testid="skills-section-error"
        message="Failed to load skills: network error"
      />,
    );
    const chip = screen.getByTestId("skills-section-error");
    // WAI-ARIA: role="alert" announces changes immediately.
    // The per-section chip inherits the page-level precedent
    // (page uses role="alert" on its events blocking-fetch error
    // banner per a11y audit D1).
    expect(chip).toHaveAttribute("role", "alert");
  });

  it("renders the message verbatim preserving any prefix", () => {
    // The chip is intentionally dumb about message formatting;
    // the caller composes the section-specific prefix
    // ("Failed to load squads: ...") upstream. This test pins
    // the contract so a future refactor doesn't accidentally
    // wrap the message in any way.
    render(
      <SectionErrorChip
        testid="timeline-section-error"
        message="Failed to load timeline: 404 Not Found"
      />,
    );
    expect(screen.getByTestId("timeline-section-error")).toHaveTextContent(
      "Failed to load timeline: 404 Not Found",
    );
  });
});
