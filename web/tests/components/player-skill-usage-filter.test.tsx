/**
 * Tour 4 v0.10.13 plan 044: vitest cases for the
 * ``<PlayerSkillUsageFilter>`` Client Component.
 *
 * Location: ``web/tests/components/`` matches the vitest
 * include pattern. Mirrors ``ProfessionFilter.test.tsx`` +
 * ``target-filter.test.tsx``.
 *
 * The component is a URL-state-driven dropdown: it reads the
 * current ``?account=`` URL filter from props (the Server
 * Component on the page is the single source of truth for
 * URL state; the Client Component receives the canonical
 * value as a prop), mutates it via ``useRouter().push``,
 * and preserves the rest of the search params so the
 * analyst's other filters (``?window_s=``, ``?target=``,
 * ``?tab=``) persist across the per-player toggle.
 *
 * What is exercised
 * =================
 * 1. **Initial render** -- the dropdown mounts with the
 *    ``currentValue`` prop pre-selected (the 1-indexed option
 *    whose value matches the prop is marked
 *    ``selected=true``); the ``"All players"`` entry is
 *    pre-selected when the prop is null / undefined.
 * 2. **Selection updates the URL** -- changing the dropdown
 *    calls ``useRouter().push`` with the updated href
 *    (``/fights/{id}?account=NEW_VALUE`` for selected;
 *    ``/fights/{id}`` for "All players"). A pre-existing
 *    search-param baseline (``?window_s=10``) persists
 *    across the toggle.
 * 3. **Empty state** -- when ``playerAgents`` is empty (the
 *    0-player NPC-only fight case), the component returns
 *    ``null`` so the parent renders its own placeholder
 *    (the page renders ``"Failed to load player list"``
 *    in that case).
 * 4. **URL state preservation** -- a baseline of
 *    ``?window_s=10&target=2`` is kept intact when the
 *    account dropdown is toggled; the new ``?account=``
 *    is appended (or removed on "All players") without
 *    stomping the other params.
 */

 
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

// Override the global no-op mock from :file:`web/tests/setup.ts`
// so this test exercises the real filter (the same pattern as
// ``target-filter.test.tsx``).
vi.mock("@/components/PlayerSkillUsageFilter", async (importOriginal) => {
  const actual =
    await importOriginal<
      typeof import("@/components/PlayerSkillUsageFilter")
    >();
  return actual;
});

// Mock ``next/navigation`` so the test can assert on the URL
// update without rendering a real Next.js router. The mock
// returns the same ``push`` spy across calls; the per-test
// ``searchParams`` baseline is mutated by reassigning the
// spy-shared mock between ``it()`` blocks (the
// ``beforeEach`` resets to the canonical baseline).
const pushMock = vi.fn();
let searchParamsMock: URLSearchParams = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
  useSearchParams: () => searchParamsMock,
}));

import { PlayerSkillUsageFilter } from "@/components/PlayerSkillUsageFilter";

const FIGHT_ID = "abc123def456";

const SAMPLE_PLAYERS = [
  { account_name: "TestAccount.1234", label: "Fighty McFight (TestAccount.1234)" },
  { account_name: "TestAccount.5678", label: "Heal Bot (TestAccount.5678)" },
];

describe("PlayerSkillUsageFilter (Tour 4 v0.10.13 plan 044)", () => {
  beforeEach(() => {
    pushMock.mockClear();
    searchParamsMock = new URLSearchParams();
  });

  it("renders the dropdown with the 2 players + the 'All players' entry, and marks the current value as pre-selected", () => {
    render(
      <PlayerSkillUsageFilter
        currentValue="TestAccount.5678"
        playerAgents={SAMPLE_PLAYERS}
        fightId={FIGHT_ID}
      />,
    );
    const select = screen.getByTestId("player-skill-filter") as HTMLSelectElement;
    // 1 "All players" + 2 player agents = 3 <option> children.
    expect(select.options).toHaveLength(3);
    // The currently-selected option is the second player
    // (1-indexed option 3 in the dropdown: "All players" +
    // TestAccount.1234 + TestAccount.5678).
    expect(select.value).toBe("TestAccount.5678");
    // The first option is the "All players" reset entry.
    expect(select.options[0]).toHaveValue("");
    expect(select.options[0]).toHaveTextContent("All players");
    // The option labels match the ``playerAgents`` list with
    // the "All players" entry prepended.
    const labels = Array.from(select.options).map((o) => o.textContent);
    expect(labels).toEqual([
      "All players",
      "Fighty McFight (TestAccount.1234)",
      "Heal Bot (TestAccount.5678)",
    ]);
  });

  it("falls back to the 'All players' option when currentValue is null/undefined", () => {
    render(
      <PlayerSkillUsageFilter
        playerAgents={SAMPLE_PLAYERS}
        fightId={FIGHT_ID}
      />,
    );
    const select = screen.getByTestId("player-skill-filter") as HTMLSelectElement;
    // The select's ``value`` is the empty string (the
    // "All players" entry).
    expect(select.value).toBe("");
  });

  it("emits ?account=NEW_VALUE when the user picks an account", () => {
    render(
      <PlayerSkillUsageFilter
        playerAgents={SAMPLE_PLAYERS}
        fightId={FIGHT_ID}
      />,
    );
    const select = screen.getByTestId("player-skill-filter");
    fireEvent.change(select, {
      target: { value: "TestAccount.1234" },
    });
    expect(pushMock).toHaveBeenCalledTimes(1);
    // The emitted URL is ``/fights/<id>?account=<value>`` -- the
    // search-params baseline is empty so no other params leak
    // in.
    expect(pushMock).toHaveBeenCalledWith(
      `/fights/${encodeURIComponent(FIGHT_ID)}?account=TestAccount.1234`,
    );
  });

  it("emits the bare URL (drops ?account=) when the user picks 'All players'", () => {
    // When the select goes back to the "All players" option
    // (the empty value), the route must strip the param
    // entirely (NOT emit ``?account=`` with an empty value)
    // so the URL stays clean + the parser-friendly contract
    // is preserved.
    render(
      <PlayerSkillUsageFilter
        currentValue="TestAccount.1234"
        playerAgents={SAMPLE_PLAYERS}
        fightId={FIGHT_ID}
      />,
    );
    const select = screen.getByTestId("player-skill-filter");
    fireEvent.change(select, { target: { value: "" } });
    expect(pushMock).toHaveBeenCalledTimes(1);
    expect(pushMock).toHaveBeenCalledWith(
      `/fights/${encodeURIComponent(FIGHT_ID)}`,
    );
  });

  it("preserves other search params (e.g. window_s + target) when the user toggles the account", () => {
    // The Server Component on the page is the SINGLE source
    // of truth for URL state; the filter's URL update must
    // not stomp on the analyst's other filter selections.
    // The mock's ``searchParams`` baseline is
    // ``window_s=10&target=2`` (set in ``beforeEach`` of a
    // dedicated test below). We override the baseline here.
    searchParamsMock = new URLSearchParams("window_s=10&target=2");
    render(
      <PlayerSkillUsageFilter
        playerAgents={SAMPLE_PLAYERS}
        fightId={FIGHT_ID}
      />,
    );
    const select = screen.getByTestId("player-skill-filter");
    fireEvent.change(select, {
      target: { value: "TestAccount.5678" },
    });
    expect(pushMock).toHaveBeenCalledTimes(1);
    // The emitted URL has the existing params intact AND the
    // new ``account`` param appended. Search-param ordering
    // is implementation-detail of ``URLSearchParams.toString()``
    // so we assert on the structural shape rather than
    // exact string equality.
    const [emittedHref] = pushMock.mock.calls[0];
    expect(emittedHref).toMatch(/^\/fights\//);
    expect(emittedHref).toMatch(/[?&]account=TestAccount\.5678/);
    expect(emittedHref).toMatch(/window_s=10/);
    expect(emittedHref).toMatch(/target=2/);
  });

  it("emits null when playerAgents is empty (0-player / NPC-only fight)", () => {
    // The 0-player edge case: the parent page already shows
    // the "Failed to load player list" message OR the
    // "no players available" placeholder; this filter is a
    // no-op in that case so the parent renders its own
    // placeholder without a duplicate or competing render
    // target.
    const { container } = render(
      <PlayerSkillUsageFilter
        playerAgents={[]}
        fightId={FIGHT_ID}
      />,
    );
    // The component returns null -- the testid is NOT in
    // the DOM and the container's HTML is empty.
    expect(container).toBeEmptyDOMElement();
    expect(
      screen.queryByTestId("player-skill-filter"),
    ).not.toBeInTheDocument();
  });

  it("URL-encodes the fight_id in the emitted href (reserved-char defensiveness)", () => {
    // Defensive: an exotic fight-id with reserved chars
    // (slashes, ampersands, etc.) would be misparsed by
    // Next.js routing if not encoded. The component uses
    // ``encodeURIComponent(fightId)`` so the test pins the
    // contract here.
    const exoticFightId = "has space&slash?param=value";
    render(
      <PlayerSkillUsageFilter
        playerAgents={SAMPLE_PLAYERS}
        fightId={exoticFightId}
      />,
    );
    const select = screen.getByTestId("player-skill-filter");
    fireEvent.change(select, {
      target: { value: "TestAccount.1234" },
    });
    const [emittedHref] = pushMock.mock.calls[0];
    expect(emittedHref).toContain(encodeURIComponent(exoticFightId));
    expect(emittedHref).not.toContain(exoticFightId);
  });
});
