/**
 * Tour 4 v0.10.13 plan 044: vitest cases for the
 * ``<PlayerSkillUsageTable>`` Client Component.
 *
 * Location: ``web/tests/components/`` matches the vitest include
 * pattern (the tests directory, all ``.test.tsx`` files) so the
 * test is picked up by ``pnpm test:unit`` without needing a
 * vitest config change. The test imports the component via the
 * ``@/`` alias to mirror the production import path.
 *
 * Test strategy
 * =============
 * The component is pure-render (no useState/useEffect hooks; the
 * surrounding page mutates the ``playerSkills`` prop when the
 * analyst picks a new account). The 6 cases below cover the
 * render chrome (the loadout header strip + the skill table +
 * the empty-state panel), the equipped-skill V1-stub text, the
 * CSV-button conditional visibility (filename + non-empty
 * skills are the AND-gate), and a couple of edge cases that
 * a future regression would silently mask.
 *
 * Why fireEvent not userEvent
 * ----------------------------
 * The component has no event handlers -- it is a pure
 * presentational render. ``fireEvent`` is unused here; the
 * assertions are on the rendered DOM shape, not on event
 * dispatch.
 */

/* eslint-disable @typescript-eslint/no-require-imports */
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { PlayerSkillUsageTable } from "@/components/PlayerSkillUsageTable";
import type { PlayerSkills } from "@/lib/api/fights";

/**
 * ``tests/setup.ts`` mocks ``@/components/PlayerSkillUsageTable`` as a
 * no-op ``() => null`` so the page-level Server Component tests can
 * render the wrapper without coupling to the table's HTML shape.
 * The component-level test in THIS file needs the real implementation
 * (it asserts on the loadout strip + skill table + empty-state panel
 * + CSV button visibility). ``vi.unmock`` is hoisted by vitest's
 * transformer to the same module-init boundary as ``vi.mock``, so the
 * unmock takes effect before the import above.
 */
vi.unmock("@/components/PlayerSkillUsageTable");

// HERMETIC FIXTURE: a populated per-player payload (3 skill rows
// for one player in one fight). Mirrors the canonical wire shape
// of :class:`PlayerSkillsOut` so a regression in the type
// contract would surface here as a TS compile error too.
function makePlayerSkills(
  overrides: Partial<PlayerSkills> = {},
): PlayerSkills {
  return {
    fight_id: "abc123def456",
    account_name: "TestAccount.1234",
    agent_id: 1234,
    loadout: {
      profession: "Warrior",
      elite_spec: "Berserker",
      equipped_skill_ids: [],
    },
    skills: [
      {
        skill_id: 100,
        skill_name: "Whirlwind",
        hit_count: 2,
        total_damage: 3000,
        total_healing: 0,
        total_buff_removal: 0,
      },
      {
        skill_id: 200,
        skill_name: "Healing Signet",
        hit_count: 1,
        total_damage: 0,
        total_healing: 567,
        total_buff_removal: 0,
      },
      {
        skill_id: 300,
        skill_name: "Strip Shot",
        hit_count: 1,
        total_damage: 0,
        total_healing: 0,
        total_buff_removal: 333,
      },
    ],
    ...overrides,
  };
}

describe("PlayerSkillUsageTable (Tour 4 v0.10.13 plan 044)", () => {
  it("renders the loadout bar + the account cell + the skill table when skills are populated", () => {
    const playerSkills = makePlayerSkills();
    render(<PlayerSkillUsageTable playerSkills={playerSkills} />);

    // Loadout header strip (4 cells: account + profession +
    // elite spec + equipped skills).
    expect(screen.getByTestId("player-skill-loadout")).toBeInTheDocument();
    // The account cell carries the canonical testid so the
    // §6 frontend quick-scans can find it without a label
    // query.
    expect(screen.getByTestId("player-skill-account")).toHaveTextContent(
      "TestAccount.1234",
    );
    // The skill table (per-player per-skill roll-up).
    expect(screen.getByTestId("player-skill-table")).toBeInTheDocument();
    // The empty-state panel is NOT rendered when skills are
    // populated.
    expect(
      screen.queryByTestId("player-skill-empty"),
    ).not.toBeInTheDocument();
  });

  it("renders the skill table rows with the right column shape (skill_id + skill_name + 3 right-aligned totals)", () => {
    const playerSkills = makePlayerSkills();
    render(<PlayerSkillUsageTable playerSkills={playerSkills} />);

    // The first skill row carries the canonical player-skill
    // labels. skill_name "Whirlwind" + totals "2 / 3,000 / 0 / 0".
    expect(screen.getByText("Whirlwind")).toBeInTheDocument();
    expect(screen.getByText("3,000")).toBeInTheDocument();
    // Healing cell has the accent colour token applied (the
    // CSS variable on the inline style). The presence of the
    // "567" cell is sufficient to assert the column renders.
    expect(screen.getByText("567")).toBeInTheDocument();
    // Strip cell carries the row's total_buff_removal value.
    expect(screen.getByText("333")).toBeInTheDocument();
  });

  it("renders the empty-state panel when the player is idle (skills: [])", () => {
    const playerSkills = makePlayerSkills({ skills: [] });
    render(<PlayerSkillUsageTable playerSkills={playerSkills} />);

    // The empty-state panel renders (matches the canonical
    // v0.8.0 §8.4 always-render pattern from
    // PerFightTimelineSection).
    expect(screen.getByTestId("player-skill-empty")).toBeInTheDocument();
    // The skill table is NOT rendered.
    expect(screen.queryByTestId("player-skill-table")).not.toBeInTheDocument();
    // The loadout strip is still rendered (it's the
    // account/profession/elite-spec header which is independent
    // of the skill rollup count).
    expect(screen.getByTestId("player-skill-loadout")).toBeInTheDocument();
    // The empty-state copy mentions the parser-zero-events
    // case so the analyst sees why the section is empty
    // (rather than assuming the dropdown broke).
    expect(screen.getByText(/no skill roll-up rows/i)).toBeInTheDocument();
  });

  it("renders the 'parser extraction deferred' stub message for equipped_skill_ids=[]", () => {
    // Backend V1 stub: parser-layer equipped-skill extraction
    // is deferred to v0.11.0. The frontend surfaces this
    // explicitly so the analyst doesn't mistake the empty
    // list for "0 skills parsed". Same contract for
    // ``equipped_skill_ids: undefined`` (defensive).
    const playerSkills = makePlayerSkills({
      loadout: {
        profession: "Warrior",
        elite_spec: "Berserker",
        equipped_skill_ids: [],
      },
    });
    render(<PlayerSkillUsageTable playerSkills={playerSkills} />);
    expect(screen.getByText(/parser extraction deferred/i)).toBeInTheDocument();
  });

  it("renders the parser-deferred text when equipped_skill_ids is undefined (defensive optionality)", () => {
    // Tour 4 commit 4 made the TS field optional (``?: number[]``)
    // to guard against future wire-format drift. The component
    // MUST treat the undefined case identically to [].
    const playerSkills = makePlayerSkills({
      loadout: {
        profession: "Warrior",
        elite_spec: "Berserker",
        // ``equipped_skill_ids`` is intentionally omitted.
      },
    });
    render(<PlayerSkillUsageTable playerSkills={playerSkills} />);
    expect(screen.getByText(/parser extraction deferred/i)).toBeInTheDocument();
  });

  it("renders the equipped-skill ids verbatim when equipped_skill_ids has values", () => {
    // Forward-compat test: once the parser-layer extracts the
    // equipped-skill IDs (the v0.11.0 ticket), the frontend
    // should render the comma-joined list. Pin the contract
    // here so a refactor that breaks the stripper is caught.
    const playerSkills = makePlayerSkills({
      loadout: {
        profession: "Warrior",
        elite_spec: "Berserker",
        equipped_skill_ids: [101, 202, 303],
      },
    });
    render(<PlayerSkillUsageTable playerSkills={playerSkills} />);
    expect(screen.getByText("101, 202, 303")).toBeInTheDocument();
    // The parser-deferred fallback text does NOT render.
    expect(
      screen.queryByText(/parser extraction deferred/i),
    ).not.toBeInTheDocument();
  });

  it("renders the '(unnamed)' fallback for a skill row with skill_name=''", () => {
    // The aggregated skill-usage row from the gateway can have
    // an empty ``skill_name`` for unknown skills (the parser
    // surfaces it as the empty string). The table renders the
    // ``(unnamed)`` fallback in that slot so the row is still
    // identifiable by its skill_id.
    const playerSkills = makePlayerSkills({
      skills: [
        {
          skill_id: 999,
          skill_name: "",
          hit_count: 1,
          total_damage: 100,
          total_healing: 0,
          total_buff_removal: 0,
        },
      ],
    });
    render(<PlayerSkillUsageTable playerSkills={playerSkills} />);
    expect(screen.getByText("(unnamed)")).toBeInTheDocument();
  });

  it("renders the CSV download button when filename is provided AND skills is non-empty", () => {
    const playerSkills = makePlayerSkills();
    render(
      <PlayerSkillUsageTable
        playerSkills={playerSkills}
        filename="fight-player-skills.csv"
      />,
    );
    // CsvDownloadButton carries its own testid + label. We don't
    // assert on the testid explicitly (that's an implementation
    // detail of CsvDownloadButton) -- we assert on the visible
    // button label so a CsvDownloadButton refactor doesn't break
    // this test.
    expect(
      screen.getByRole("button", { name: /download csv/i }),
    ).toBeInTheDocument();
  });

  it("hides the CSV download button when skills is empty (even with filename)", () => {
    const playerSkills = makePlayerSkills({ skills: [] });
    render(
      <PlayerSkillUsageTable
        playerSkills={playerSkills}
        filename="fight-player-skills.csv"
      />,
    );
    // The CSV download button is hidden when no rows are
    // present (a CSV with just the header row would be useless
    // AND would mask the empty-state panel).
    expect(
      screen.queryByRole("button", { name: /download csv/i }),
    ).not.toBeInTheDocument();
    // The empty-state panel still renders.
    expect(screen.getByTestId("player-skill-empty")).toBeInTheDocument();
  });

  it("hides the CSV download button when filename is not provided (per the optional-prop contract)", () => {
    // The ``filename`` prop is OPTIONAL. A caller that doesn't
    // pass it gets a render-only table (no download button,
    // no wasted CPU on building the CSV blob).
    const playerSkills = makePlayerSkills();
    render(<PlayerSkillUsageTable playerSkills={playerSkills} />);
    expect(
      screen.queryByRole("button", { name: /download csv/i }),
    ).not.toBeInTheDocument();
  });
});
