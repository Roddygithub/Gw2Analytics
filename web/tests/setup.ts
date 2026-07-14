import * as React from "react";
import { vi } from "vitest";
import "@testing-library/jest-dom/vitest";

/**
 * ``@/components/FightsGrid`` is the AG Grid client wrapper. The
 * page-level Server Component tests transitively import it, but
 * booting AG Grid's full runtime in jsdom would require a real
 * DOM + canvas + the AllCommunityModule side-effects chain --
 * well out of scope for the page-render unit tests. Mocking the
 * whole component here lets the page tests render the wrapper
 * without dragging :file:`node_modules/ag-grid-react` into the
 * vitest resolver. AG Grid itself is still installed (real dev
 * server, real build) -- only the test runtime substitutes it.
 *
 * ``@/components/TargetRollupsGrid`` is the AG Grid Community
 * wrapper for the per-target damage + healing roll-up tables on
 * the new ``/fights/[id]`` drill-down page (Phase 7 v1 of web).
 * The fight-events-page test transitively imports it, so it gets
 * the same no-op stub treatment here.
 *
 * ``@/components/EventWindowsTable`` is a plain HTML table (no
 * AG Grid), but we still mock it here so the page-level tests
 * can assert on the table's presence/absence without coupling
 * the assertions to the table's exact HTML shape (a future
 * styling refactor would otherwise force the test to be edited
 * in lockstep).
 *
 * NOTE: every mocked component here is a NAMED export
 * (``export function FightsGrid(...)`` /
 * ``export function TargetRollupsGrid(...)`` /
 * ``export function EventWindowsTable(...)``), not a default
 * export, so the mock shapes must mirror that -- not
 * ``{ default: () => null }``.
 */
vi.mock("@/components/FightsGrid", () => ({
  FightsGrid: () => null,
}));

vi.mock("@/components/TargetRollupsGrid", () => ({
  TargetRollupsGrid: () => null,
}));

vi.mock("@/components/EventWindowsTable", () => ({
  EventWindowsTable: () => null,
}));

/**
 * ``@/components/WindowSizeSelector`` is a small Client Component
 * (useRouter + usePathname from ``next/navigation``) that renders
 * a dropdown for the ``?window_s=`` query param. The fight-events-
 * page test imports the page (which transitively imports the
 * selector), so we mock it as a no-op to keep the page test
 * focused on the page's own render contract; a dedicated
 * component-level test in
 * :file:`web/tests/components/window-size-selector.test.tsx`
 * exercises the dropdown + router interaction.
 */
vi.mock("@/components/WindowSizeSelector", () => ({
  WindowSizeSelector: () => null,
}));

/**
 * ``@/components/TargetFilter`` is a small Client Component
 * (useRouter + usePathname + useSearchParams from ``next/navigation``)
 * that renders a dropdown for the ``?target=`` query param. The
 * fight-events-page test imports the page (which transitively imports
 * the filter), so we mock it as a no-op to keep the page test
 * focused on the page's own render contract; a dedicated
 * component-level test in
 * :file:`web/tests/components/target-filter.test.tsx` exercises the
 * dropdown + router interaction.
 */
vi.mock("@/components/TargetFilter", () => ({
  TargetFilter: () => null,
}));

/**
 * next/link is replaced with a plain anchor so jsdom can resolve
 * the href without booting the Next.js runtime. The original
 * ``Link`` accepts ``className`` + child React tree; the shim
 * forwards both to ``<a>`` so role-based queries still find the
 * rendered nav cards.
 */
vi.mock("next/link", () => ({
  default: ({
    children,
    href,
    className,
  }: {
    children: React.ReactNode;
    href: string;
    className?: string;
  }) => React.createElement("a", { href, className }, children),
}));

/**
 * next/font/google Google Fonts are a build-time download. jsdom has
 * no network access during tests and the font binary is irrelevant
 * to layout assertions; return inert CSS variable shims so the
 * ``className`` template literal in :file:`app/layout.tsx` still
 * types + renders.
 */
vi.mock("next/font/google", () => ({
  Geist: () => ({ variable: "--mock-sans", className: "mock-sans" }),
  Geist_Mono: () => ({ variable: "--mock-mono", className: "mock-mono" }),
}));

/**
 * @/lib/env reads ``process.env.API_BASE_URL`` at module-load. The
 * Server Components under test need a deterministic value (``http://test/api``)
 * so footer / display-URL assertions are stable across machines.
 * ``displayedApiBaseUrl`` is aliased to the same constant since
 * :file:`lib/env.ts` documents it as a derived-but-stable symbol.
 */
const API_BASE_URL = "http://test/api";
vi.mock("@/lib/env", () => ({
  API_BASE_URL,
  displayedApiBaseUrl: API_BASE_URL,
}));

/**
 * v0.7.1 of web: ``@/components/EventWindowsChart`` is a small
 * Client Component (inline SVG) for the per-fight event windows.
 * The page-level Server Component tests transitively import it,
 * so we mock it as a no-op to keep the page test focused on the
 * page's own render contract.
 */
vi.mock("@/components/EventWindowsChart", () => ({
  EventWindowsChart: () => null,
}));

/**
 * v0.7.1 of web: ``@/components/SquadRollupsGrid`` is the AG Grid
 * Community wrapper for the per-subgroup roll-up. Mocked as a
 * no-op so the page-level tests can render the wrapper without
 * dragging :file:`node_modules/ag-grid-react` into the vitest
 * resolver.
 */
vi.mock("@/components/SquadRollupsGrid", () => ({
  SquadRollupsGrid: () => null,
}));

/**
 * v0.7.1 of web: ``@/components/SkillUsageTable`` is a plain HTML
 * table (no AG Grid). Mocked as a no-op so the page-level tests
 * can assert on the table's presence/absence without coupling to
 * the table's exact HTML shape.
 */
vi.mock("@/components/SkillUsageTable", () => ({
  SkillUsageTable: () => null,
}));

/**
 * Tour 4 v0.10.13 plan 044: ``@/components/PlayerSkillUsageTable``
 * is the per-player roll-up table + loadout strip on the per-fight
 * drill-down page. The page-level Server Component tests transitively
 * import it, so we mock it as a no-op to keep the page test focused
 * on the page's own render contract; a dedicated component-level
 * test in
 * :file:`web/tests/components/player-skill-usage-table.test.tsx`
 * exercises the full render chrome (loadout bar, skill table,
 * empty-state panel, CSV button visibility).
 */
vi.mock("@/components/PlayerSkillUsageTable", () => ({
  PlayerSkillUsageTable: () => null,
}));

/**
 * Tour 4 v0.10.13 plan 044: ``@/components/PlayerSkillUsageFilter``
 * is the per-player dropdown Client Component that drives the
 * ``?account=`` URL search-param on ``/fights/[id]``. Mocked as a
 * no-op at the page-level test layer so the page test can assert
 * on the per-player section's wrapping chrome without booting the
 * Next.js router; a dedicated component-level test in
 * :file:`web/tests/components/player-skill-usage-filter.test.tsx`
 * exercises the dropdown + ``router.push`` interaction directly.
 */
vi.mock("@/components/PlayerSkillUsageFilter", () => ({
  PlayerSkillUsageFilter: () => null,
}));

/**
 * v0.7.1 of web: ``@/components/PlayersGrid`` is the AG Grid
 * Community wrapper for the ``/players`` paginated list. Mocked
 * as a no-op so the page-level tests can render the wrapper
 * without dragging AG Grid's runtime into jsdom.
 */
vi.mock("@/components/PlayersGrid", () => ({
  PlayersGrid: () => null,
}));

/**
 * v0.7.1 of web: ``@/components/PlayerSearchBar`` is a small
 * Client Component (useRouter + useState) that renders the
 * header-bar search input. The layout test transitively imports
 * it, so we mock it as a no-op; a dedicated component-level
 * test in
 * :file:`web/tests/components/player-search-bar.test.tsx`
 * exercises the form submit + router interaction.
 */
vi.mock("@/components/PlayerSearchBar", () => ({
  PlayerSearchBar: () => null,
}));

/**
 * v0.8.0 of web: ``@/components/PlayerTimelineSection`` is the
 * Client Component wrapper for the per-account historical
 * timeline (handles the "Load more" pagination). Mocked as a
 * no-op so the page-level tests can render the wrapper
 * without booting the React useState + fetch plumbing; a
 * dedicated component-level test in
 * :file:`web/tests/components/player-timeline-section.test.tsx`
 * exercises the button click + state-update contract.
 */
vi.mock("@/components/PlayerTimelineSection", () => ({
  PlayerTimelineSection: () => null,
}));



/**
 * v0.8.9 of web (plan/002): ``@/components/PerFightTimelineSection``
 * is the Server Component wrapper for the per-fight timeline
 * section on the ``/fights/[id]`` page. The page-level Server
 * Component tests transitively import it, so we mock it as a
 * no-op to keep the page test focused on the page's own render
 * contract; a dedicated component-level test in
 * :file:`web/tests/components/per-fight-timeline-chart.test.tsx`
 * exercises the chart's pure-helper output. The page-level
 * presence/absence assertion lives in
 * :file:`web/tests/e2e/fights.spec.ts`.
 */
vi.mock("@/components/PerFightTimelineSection", () => ({
  PerFightTimelineSection: () => null,
}));/**
 * v0.8.9 of web (plan/002): ``@/components/PerFightTimelineChart``
 * is the inline-SVG Client Component for the per-fight timeline
 * chart. We do NOT mock it here: the page-level Server
 * Component tests mock ``@/components/PerFightTimelineSection``
 * (the section wrapper) as ``() => null`` (see above), which
 * prevents the chart from ever rendering in page-level tests
 * regardless of whether the chart itself is mocked. Leaving the
 * chart unmocked lets the dedicated component-level test in
 * :file:`web/tests/components/per-fight-timeline-chart.test.tsx`
 * render the real SVG and exercise the pure helpers
 * (``buildPerFightTimelineLayout`` + ``formatPerFightLogTick``)
 * directly. A previous version of this setup mocked the chart
 * with ``importOriginal`` to keep the pure helpers available,
 * but that approach replaced the React component with
 * ``() => null`` -- which silently broke the component-level
 * test (it rendered nothing, so ``querySelectorAll( "text" )``
 * returned an empty array). The fix is to mock the section
 * wrapper (which is the actual page-level concern) and let the
 * chart be tested directly at the component level.
 */

/**
 * Tour 6 Wave 7 (Workstream F): ``@/components/PlayerReadoutDamage``
 * is the AG Grid Community 34 Client Component for the Combat
 * readout §3 Damage table (per docs/v0.9.0-combat-readout-design.md).
 * Mocked as a no-op at the page-level test layer so the page test
 * can render the wrapper without booting AG Grid's runtime in
 * jsdom (no canvas, no offsetWidth). A dedicated component-level
 * test in :file:`web/tests/components/combat-readout.test.tsx`
 * exercises the column defs + default sort + empty-state panel.
 */
vi.mock("@/components/PlayerReadoutDamage", () => ({
  PlayerReadoutDamage: () => null,
}));

/**
 * Tour 6 Wave 7 (Workstream F): ``@/components/PlayerReadoutHeal``.
 * Mocked as a no-op at the page-level test layer; component-level
 * coverage lives in :file:`web/tests/components/combat-readout.test.tsx`.
 */
vi.mock("@/components/PlayerReadoutHeal", () => ({
  PlayerReadoutHeal: () => null,
}));

/**
 * Tour 6 Wave 7 (Workstream F): ``@/components/PlayerReadoutBoons``.
 * Mocked as a no-op at the page-level test layer; the dynamic
 * ``other_boons_total`` ``valueGetter`` is exercised at the
 * component level in :file:`web/tests/components/combat-readout.test.tsx`.
 */
vi.mock("@/components/PlayerReadoutBoons", () => ({
  PlayerReadoutBoons: () => null,
}));

/**
 * Tour 6 Wave 7 (Workstream F): ``@/components/PlayerReadoutDefense``.
 * Mocked as a no-op at the page-level test layer; component-level
 * coverage lives in :file:`web/tests/components/combat-readout.test.tsx`.
 */
vi.mock("@/components/PlayerReadoutDefense", () => ({
  PlayerReadoutDefense: () => null,
}));
