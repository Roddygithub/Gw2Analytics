"use client";

/**
 * Player positioning metrics (stack_dist + dist_to_com).
 *
 * v0.11.0 Phase C: Fetches per-player positioning data from
 * ``GET /fights/{id}/positions`` and renders an HTML table of
 * ``stack_dist`` (average distance to all other players) and
 * ``dist_to_com`` (average distance to the squad's center of mass).
 */

import { useCallback, useEffect, useState } from "react";

import { fetchFightPositions, type PlayerPositionOut } from "@/lib/api";

interface PlayerPositionRow {
  account_name: string;
  name: string;
  profession: string;
  elite_spec: string;
  stack_dist: number | null;
  dist_to_com: number | null;
  sample_count: number;
}

interface PlayerPositionGridProps {
  fightId: string;
}

export function PlayerPositionGrid({ fightId }: PlayerPositionGridProps) {
  const [rows, setRows] = useState<PlayerPositionRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadPositions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchFightPositions(fightId);
      setRows(
        data.players.map((p: PlayerPositionOut) => ({
          account_name: p.account_name,
          name: p.name,
          profession: p.profession,
          elite_spec: p.elite_spec,
          stack_dist: p.stack_dist ?? null,
          dist_to_com: p.dist_to_com ?? null,
          sample_count: p.samples?.length ?? 0,
        })),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load positions");
    } finally {
      setLoading(false);
    }
  }, [fightId]);

  useEffect(() => {
    loadPositions();
  }, [loadPositions]);

  if (loading) {
    return <p className="text-muted-foreground p-4">Loading positions…</p>;
  }
  if (error) {
    return <p className="text-destructive p-4">Error: {error}</p>;
  }
  if (rows.length === 0) {
    return (
      <p className="text-muted-foreground p-4">
        No position data available for this fight.
      </p>
    );
  }

  const fmtDist = (v: number | null): string =>
    v !== null && v !== undefined ? `${v.toFixed(1)} u` : "—";

  return (
    <section
      className="w-full overflow-auto"
      data-testid="player-position-grid"
    >
      <table className="min-w-full border-collapse text-sm">
        <thead>
          <tr className="border-b bg-muted/50">
            <th scope="col" className="px-3 py-2 text-left font-medium">
              Nom
            </th>
            <th scope="col" className="px-3 py-2 text-left font-medium">
              Profil
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              Stack dist
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              Dist COM
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              Échantillons
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.account_name} className="border-b hover:bg-muted/30">
              <td className="px-3 py-2">{r.name}</td>
              <td className="px-3 py-2 text-muted-foreground">
                {r.elite_spec}
              </td>
              <td className="px-3 py-2 text-right font-mono tabular-nums">
                {fmtDist(r.stack_dist)}
              </td>
              <td className="px-3 py-2 text-right font-mono tabular-nums">
                {fmtDist(r.dist_to_com)}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">
                {r.sample_count.toLocaleString()}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
