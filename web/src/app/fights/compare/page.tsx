"use client";

/**
 * Fight comparison page — select two fights and view their combat
 * readout tables (Damage, Heal, Boons, Defense) side by side.
 *
 * Why a Client Component
 * ======================
 * The page needs interactivity (two dropdowns, dynamic data fetching
 * when the user picks a fight). All data fetching happens on the
 * client via the shared API functions (fetchFights + fetchFightReadout).
 *
 * URL state
 * =========
 * The selected fights are stored in URL query params (``?a=<id>&b=<id>``)
 * so the comparison is URL-permalinkable (shareable/bookmarkable).
 */
import React, { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";

import {
  fetchFights,
  fetchFightReadout,
  type FightRow,
  type FightReadoutOut,
} from "@/lib/api";
import { PlayerReadoutDamage } from "@/components/PlayerReadoutDamage";
import { PlayerReadoutHeal } from "@/components/PlayerReadoutHeal";
import { PlayerReadoutBoons } from "@/components/PlayerReadoutBoons";
import { PlayerReadoutDefense } from "@/components/PlayerReadoutDefense";
import { FightSummaryCards } from "@/components/FightSummaryCards";

const CONTAINER: React.CSSProperties = {
  padding: "32px",
  display: "flex",
  flexDirection: "column",
  gap: 24,
  maxWidth: 1600,
  margin: "0 auto",
};

const SELECT_STYLE: React.CSSProperties = {
  padding: "8px 12px",
  borderRadius: 4,
  border: "1px solid var(--border)",
  background: "var(--surface)",
  color: "var(--foreground)",
  fontSize: 14,
  fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
  flex: 1,
  minWidth: 200,
};

const FIGHT_CARD: React.CSSProperties = {
  flex: 1,
  minWidth: 0,
  display: "flex",
  flexDirection: "column",
  gap: 16,
};

const FIGHT_HEADER: React.CSSProperties = {
  padding: "12px 16px",
  border: "1px solid var(--border)",
  borderRadius: 4,
  background: "var(--surface)",
  fontSize: 13,
};

const EMPTY_STATE: React.CSSProperties = {
  padding: "32px",
  textAlign: "center",
  opacity: 0.7,
  border: "1px dashed var(--border)",
  borderRadius: 4,
  color: "var(--foreground)",
};

/** Inner component that uses useSearchParams (needs Suspense wrapper). */
function FightCompareInner() {
  const searchParams = useSearchParams();
  const router = useRouter();

  const [fights, setFights] = useState<FightRow[]>([]);
  const [fightsLoading, setFightsLoading] = useState(true);
  const [fightsError, setFightsError] = useState<string | null>(null);

  const fightAId = searchParams.get("a") ?? null;
  const fightBId = searchParams.get("b") ?? null;

  const [readoutA, setReadoutA] = useState<FightReadoutOut | null>(null);
  const [readoutB, setReadoutB] = useState<FightReadoutOut | null>(null);
  const [loadingA, setLoadingA] = useState(false);
  const [loadingB, setLoadingB] = useState(false);
  const [errorA, setErrorA] = useState<string | null>(null);
  const [errorB, setErrorB] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const rows = await fetchFights();
        if (!cancelled) {
          setFights(rows);
          setFightsLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          setFightsError(err instanceof Error ? err.message : String(err));
          setFightsLoading(false);
        }
      }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!fightAId) return;
    let cancelled = false;
    setReadoutA(null);
    setLoadingA(true);
    setErrorA(null);
    (async () => {
      try {
        const data = await fetchFightReadout(fightAId);
        if (!cancelled) {
          setReadoutA(data);
          setLoadingA(false);
        }
      } catch (err) {
        if (!cancelled) {
          setErrorA(err instanceof Error ? err.message : String(err));
          setLoadingA(false);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [fightAId]);

  useEffect(() => {
    if (!fightBId) return;
    let cancelled = false;
    setReadoutB(null);
    setLoadingB(true);
    setErrorB(null);
    (async () => {
      try {
        const data = await fetchFightReadout(fightBId);
        if (!cancelled) {
          setReadoutB(data);
          setLoadingB(false);
        }
      } catch (err) {
        if (!cancelled) {
          setErrorB(err instanceof Error ? err.message : String(err));
          setLoadingB(false);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [fightBId]);

  const updateFight = useCallback(
    (slot: "a" | "b", fightId: string) => {
      const params = new URLSearchParams(searchParams.toString());
      params.set(slot, fightId);
      router.push(`/fights/compare?${params.toString()}`);
    },
    [searchParams, router],
  );

  const optionsA = fights.filter((f) => f.id !== fightBId);
  const optionsB = fights.filter((f) => f.id !== fightAId);

  const shortId = (id: string) => id.slice(0, 12) + "…";

  const fightAInfo = useMemo(
    () => fights.find((f) => f.id === fightAId),
    [fights, fightAId],
  );
  const fightBInfo = useMemo(
    () => fights.find((f) => f.id === fightBId),
    [fights, fightBId],
  );

  return (
    <main style={CONTAINER}>
      <header>
        <p style={{ marginBottom: 8 }}>
          <a
            href="/fights"
            style={{
              color: "var(--accent)",
              fontSize: 13,
              textDecoration: "none",
            }}
          >
            &larr; Back to fights
          </a>
        </p>
        <h1 style={{ fontSize: 28, marginBottom: 4 }}>
          Compare fights
        </h1>
        <p style={{ opacity: 0.7, fontSize: 14 }}>
          Select two fights to compare their combat readout side by side.
        </p>
      </header>

      <section
        style={{
          display: "flex",
          gap: 16,
          flexWrap: "wrap",
          alignItems: "center",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 4, flex: 1 }}>
          <label style={{ fontSize: 12, opacity: 0.7, fontWeight: 600 }}>
            Fight A
          </label>
          <select
            value={fightAId ?? ""}
            onChange={(e) => updateFight("a", e.target.value)}
            style={SELECT_STYLE}
            disabled={fightsLoading}
          >
            <option value="">— Select a fight —</option>
            {optionsA.map((f) => (
              <option key={f.id} value={f.id}>
                {shortId(f.id)} ({f.agent_count} agents, {f.started_at?.slice(0, 10) ?? "?"})
              </option>
            ))}
          </select>
        </div>

        <span
          style={{
            fontSize: 18,
            fontWeight: 600,
            opacity: 0.5,
            paddingTop: 16,
          }}
        >
          VS
        </span>

        <div style={{ display: "flex", flexDirection: "column", gap: 4, flex: 1 }}>
          <label style={{ fontSize: 12, opacity: 0.7, fontWeight: 600 }}>
            Fight B
          </label>
          <select
            value={fightBId ?? ""}
            onChange={(e) => updateFight("b", e.target.value)}
            style={SELECT_STYLE}
            disabled={fightsLoading}
          >
            <option value="">— Select a fight —</option>
            {optionsB.map((f) => (
              <option key={f.id} value={f.id}>
                {shortId(f.id)} ({f.agent_count} agents, {f.started_at?.slice(0, 10) ?? "?"})
              </option>
            ))}
          </select>
        </div>
      </section>

      {fightsError && (
        <p style={{ color: "var(--accent)", fontSize: 13 }}>
          Failed to load fights: {fightsError}
        </p>
      )}
      {fightsLoading && fights.length === 0 && (
        <p style={{ opacity: 0.7, fontSize: 13 }}>Loading fights…</p>
      )}

      {(fightAId || fightBId) && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 24,
          }}
        >
          <div style={FIGHT_CARD}>
            {loadingA && <p style={{ opacity: 0.7, fontSize: 13 }}>Loading Fight A…</p>}
            {errorA && (
              <p style={{ color: "var(--accent)", fontSize: 13 }}>
                Error: {errorA}
              </p>
            )}
            {!fightAId && (
              <div style={EMPTY_STATE}>Select a fight for this slot.</div>
            )}
            {readoutA && (
              <FightColumn
                label="Fight A"
                fightId={fightAId!}
                readout={readoutA}
                fightInfo={fightAInfo}
              />
            )}
          </div>

          <div style={FIGHT_CARD}>
            {loadingB && <p style={{ opacity: 0.7, fontSize: 13 }}>Loading Fight B…</p>}
            {errorB && (
              <p style={{ color: "var(--accent)", fontSize: 13 }}>
                Error: {errorB}
              </p>
            )}
            {!fightBId && (
              <div style={EMPTY_STATE}>Select a fight for this slot.</div>
            )}
            {readoutB && (
              <FightColumn
                label="Fight B"
                fightId={fightBId!}
                readout={readoutB}
                fightInfo={fightBInfo}
              />
            )}
          </div>
        </div>
      )}

      {!fightAId && !fightBId && fights.length > 0 && (
        <div style={EMPTY_STATE}>
          Select two fights from the dropdowns above to compare their combat
          readout side by side.
        </div>
      )}
    </main>
  );
}

/** One column of the side-by-side comparison. */
function FightColumn({
  label,
  fightId,
  readout,
  fightInfo,
}: {
  label: string;
  fightId: string;
  readout: FightReadoutOut;
  fightInfo?: FightRow;
}) {
  return (
    <>
      <div style={FIGHT_HEADER}>
        <strong>{label}</strong>
        {fightInfo && (
          <>
            {" · "}
            {fightInfo.agent_count} players ·{" "}
            {fightInfo.started_at?.slice(0, 10) ?? "?"} ·{" "}
            {readout.duration_s.toFixed(1)}s
          </>
        )}
        <br />
        <a
          href={`/fights/${encodeURIComponent(fightId)}`}
          style={{
            color: "var(--accent)",
            fontSize: 11,
            textDecoration: "none",
            opacity: 0.8,
          }}
        >
          {fightId.slice(0, 16)}…
        </a>
      </div>

      {readout.players.length > 0 && (
        <FightSummaryCards players={readout.players} />
      )}

      <section style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div>
          <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>
            Damage
          </h3>
          <PlayerReadoutDamage rows={readout.players} />
        </div>
        <div>
          <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>
            Heal
          </h3>
          <PlayerReadoutHeal rows={readout.players} />
        </div>
        <div>
          <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>
            Boons
          </h3>
          <PlayerReadoutBoons rows={readout.players} />
        </div>
        <div>
          <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>
            Defense
          </h3>
          <PlayerReadoutDefense rows={readout.players} />
        </div>
      </section>
    </>
  );
}

/** Page wrapper with Suspense boundary for useSearchParams. */
export default function FightComparePage() {
  return (
    <Suspense
      fallback={
        <main style={CONTAINER}>
          <p style={{ opacity: 0.7 }}>Loading compare page…</p>
        </main>
      }
    >
      <FightCompareInner />
    </Suspense>
  );
}
