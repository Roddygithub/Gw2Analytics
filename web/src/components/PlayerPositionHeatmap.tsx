"use client";

/**
 * Player position heatmap — 2D canvas rendering of squad positions
 * over time.
 *
 * v0.14.3 Phase H: Fetches per-player position samples from
 * ``GET /fights/{id}/positions`` and renders a top-down 2D view
 * with profession-colored dots, movement trails, a center-of-mass
 * crosshair, and a time slider with play/pause animation.
 *
 * Coordinates are auto-scaled to fit the canvas; the origin (0,0)
 * is centered. Trails show the last 4 seconds of movement with
 * fading opacity. Labels display short player names. The COM
 * marker is a white crosshair.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import React from "react";

import { fetchFightPositions, type PlayerPositionOut } from "@/lib/api";
import {
  FALLBACK_COLOR,
  PROFESSION_COLORS,
  professionColor,
} from "@/lib/professionColors";

// ---------------------------------------------------------------------------
// Canvas constants
// ---------------------------------------------------------------------------

const COM_COLOR = "#FFFFFF";
const TRAIL_FADE_MS = 4000;
const SAMPLE_INTERVAL_MS = 500;
const DOT_RADIUS = 6;
const COM_RADIUS = 8;
const LABEL_OFFSET = 10;
const CANVAS_PADDING = 40;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface HeatmapPlayer {
  account_name: string;
  name: string;
  profession: string;
  elite_spec: string;
  /** Samples at 500 ms intervals: [[time_ms, x, y], ...] (built from
   *  the wire samples array + implicit 500 ms spacing). */
  samples: [number, number, number][];
}

interface PlayerPositionHeatmapProps {
  fightId: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function PlayerPositionHeatmap({ fightId }: PlayerPositionHeatmapProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const animRef = useRef<number | null>(null);

  const [players, setPlayers] = useState<HeatmapPlayer[]>([]);
  const [durationMs, setDurationMs] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // ---- data fetching --------------------------------------------------------

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchFightPositions(fightId);
      const built: HeatmapPlayer[] = data.players.map((p: PlayerPositionOut) => {
        const samples: [number, number, number][] = (p.samples ?? []).map(
          (s, i) => [i * SAMPLE_INTERVAL_MS, s.x, s.y] as [number, number, number],
        );
        return {
          account_name: p.account_name,
          name: p.name,
          profession: p.profession,
          elite_spec: p.elite_spec,
          samples,
        };
      });
      setPlayers(built);
      const maxT = Math.max(0, ...built.flatMap((p) => p.samples.map((s) => s[0])));
      setDurationMs(maxT);
      setCurrentTime(0);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load positions");
    } finally {
      setLoading(false);
    }
  }, [fightId]);

  useEffect(() => {
    load();
  }, [load]);

  // ---- animation loop -------------------------------------------------------

  useEffect(() => {
    if (!playing || durationMs === 0) return;
    let last = performance.now();
    const tick = (now: number) => {
      const delta = now - last;
      last = now;
      setCurrentTime((prev) => {
        const next = prev + delta;
        return next >= durationMs ? durationMs : next;
      });
      animRef.current = requestAnimationFrame(tick);
    };
    animRef.current = requestAnimationFrame(tick);
    return () => {
      if (animRef.current !== null) cancelAnimationFrame(animRef.current);
    };
  }, [playing, durationMs]);

  // stop playing when we hit the end
  useEffect(() => {
    if (currentTime >= durationMs && playing) {
      setPlaying(false);
    }
  }, [currentTime, durationMs, playing]);

  // ---- canvas drawing (handles DPR sizing internally) -----------------------

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    // Responsive sizing: match canvas backing store to CSS layout
    // dimensions × devicePixelRatio for crisp rendering on all screens.
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    const cssW = rect.width;
    const cssH = rect.height;

    // Guard: don't draw if the canvas hasn't been laid out yet
    // (getBoundingClientRect may return 0 during initial render).
    // Retry up to 10 frames, then give up to avoid infinite loop.
    if (cssW === 0 || cssH === 0) {
      const retries = (canvas as unknown as Record<string, number>)._heatmapRetries || 0;
      if (retries < 10) {
        (canvas as unknown as Record<string, number>)._heatmapRetries = retries + 1;
        requestAnimationFrame(() => draw());
      }
      return;
    }
    (canvas as unknown as Record<string, number>)._heatmapRetries = 0;

    if (canvas.width !== cssW * dpr || canvas.height !== cssH * dpr) {
      canvas.width = cssW * dpr;
      canvas.height = cssH * dpr;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);

    // Compute viewport bounds from ALL samples so the rendering
    // is stable across the whole fight.
    const allX: number[] = [];
    const allY: number[] = [];
    for (const p of players) {
      for (const s of p.samples) {
        allX.push(s[1]);
        allY.push(s[2]);
      }
    }
    if (allX.length === 0) return;
    const minX = Math.min(...allX);
    const maxX = Math.max(...allX);
    const minY = Math.min(...allY);
    const maxY = Math.max(...allY);
    const rangeX = maxX - minX || 1;
    const rangeY = maxY - minY || 1;

    const drawW = cssW - CANVAS_PADDING * 2;
    const drawH = cssH - CANVAS_PADDING * 2;

    const toScreen = (x: number, y: number): [number, number] => [
      CANVAS_PADDING + ((x - minX) / rangeX) * drawW,
      CANVAS_PADDING + ((y - minY) / rangeY) * drawH,
    ];

    // Interpolate a player's position at time t (linear between
    // the surrounding samples).
    const interpolate = (
      samples: [number, number, number][],
      t: number,
    ): [number, number] | null => {
      if (samples.length === 0) return null;
      if (t <= samples[0][0]) return [samples[0][1], samples[0][2]];
      for (let i = 0; i < samples.length - 1; i++) {
        if (t >= samples[i][0] && t <= samples[i + 1][0]) {
          const ratio =
            (t - samples[i][0]) / (samples[i + 1][0] - samples[i][0]);
          return [
            samples[i][1] + (samples[i + 1][1] - samples[i][1]) * ratio,
            samples[i][2] + (samples[i + 1][2] - samples[i][2]) * ratio,
          ];
        }
      }
      // past the last sample
      const last = samples[samples.length - 1];
      return [last[1], last[2]];
    };

    // ---- draw grid (light reference lines for spatial orientation) ---------

    ctx.strokeStyle = "rgba(255,255,255,0.04)";
    ctx.lineWidth = 0.5;
    const gridStep = Math.max(1, Math.floor(Math.min(drawW, drawH) / 8));
    for (let gx = CANVAS_PADDING; gx <= CANVAS_PADDING + drawW; gx += gridStep) {
      ctx.beginPath();
      ctx.moveTo(gx, CANVAS_PADDING);
      ctx.lineTo(gx, CANVAS_PADDING + drawH);
      ctx.stroke();
    }
    for (let gy = CANVAS_PADDING; gy <= CANVAS_PADDING + drawH; gy += gridStep) {
      ctx.beginPath();
      ctx.moveTo(CANVAS_PADDING, gy);
      ctx.lineTo(CANVAS_PADDING + drawW, gy);
      ctx.stroke();
    }

    // ---- draw trails --------------------------------------------------------

    ctx.lineWidth = 2;
    for (const p of players) {
      const color = professionColor(p.profession);
      ctx.strokeStyle = color;
      ctx.beginPath();
      let first = true;
      for (const s of p.samples) {
        const age = currentTime - s[0];
        if (age < 0) break; // future sample
        if (age > TRAIL_FADE_MS) continue; // too old
        const alpha = 1 - age / TRAIL_FADE_MS;
        ctx.globalAlpha = alpha;
        const [sx, sy] = toScreen(s[1], s[2]);
        if (first) {
          ctx.moveTo(sx, sy);
          first = false;
        } else {
          ctx.lineTo(sx, sy);
        }
      }
      ctx.stroke();
    }
    ctx.globalAlpha = 1;

    // ---- draw current positions ---------------------------------------------

    const activePositions: [string, number, number, string][] = [];
    let comX = 0;
    let comY = 0;
    let activeCount = 0;

    for (const p of players) {
      const pos = interpolate(p.samples, currentTime);
      if (!pos) continue;
      const color = professionColor(p.profession);
      const [sx, sy] = toScreen(pos[0], pos[1]);
      activePositions.push([p.name, sx, sy, color]);
      comX += sx;
      comY += sy;
      activeCount++;
    }

    for (const [, sx, sy, color] of activePositions) {
      // Glow ring for visibility on dark background.
      ctx.fillStyle = color;
      ctx.globalAlpha = 0.15;
      ctx.beginPath();
      ctx.arc(sx, sy, DOT_RADIUS + 4, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 1;

      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(sx, sy, DOT_RADIUS, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = "#1a1a2e";
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }

    // ---- labels -------------------------------------------------------------

    ctx.font = "10px var(--font-geist-sans, sans-serif)";
    ctx.textAlign = "center";
    for (const [name, sx, sy] of activePositions) {
      ctx.fillStyle = "#e0e0e0";
      ctx.fillText(name, sx, sy + DOT_RADIUS + LABEL_OFFSET);
    }

    // ---- center of mass -----------------------------------------------------

    if (activeCount > 1) {
      comX /= activeCount;
      comY /= activeCount;
      ctx.strokeStyle = COM_COLOR;
      ctx.lineWidth = 2;
      // horizontal
      ctx.beginPath();
      ctx.moveTo(comX - COM_RADIUS, comY);
      ctx.lineTo(comX + COM_RADIUS, comY);
      ctx.stroke();
      // vertical
      ctx.beginPath();
      ctx.moveTo(comX, comY - COM_RADIUS);
      ctx.lineTo(comX, comY + COM_RADIUS);
      ctx.stroke();
    }
  }, [players, currentTime]);

  useEffect(() => {
    draw();
  }, [draw]);

  // ---- helpers --------------------------------------------------------------

  const fmtTime = (ms: number): string => {
    const s = Math.floor(ms / 1000);
    const m = Math.floor(s / 60);
    return `${m}:${String(s % 60).padStart(2, "0")}`;
  };

  // ---- render ---------------------------------------------------------------

  if (loading) {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height: 420,
          color: "var(--muted-foreground)",
          fontSize: 14,
        }}
      >
        Chargement des positions…
      </div>
    );
  }
  if (error) {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height: 420,
          color: "var(--accent)",
          fontSize: 14,
        }}
      >
        Erreur : {error}
      </div>
    );
  }
  if (players.length === 0) {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height: 420,
          color: "var(--muted-foreground)",
          fontSize: 14,
        }}
      >
        Aucune donnée de position pour ce combat.
      </div>
    );
  }

  return (
    <section
      data-testid="player-position-heatmap"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 12,
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: 8,
        padding: 16,
      }}
    >
      {/* ---- canvas ---- */}
      <canvas
        ref={canvasRef}
        width={800}
        height={400}
        role="img"
        aria-label={`Carte des positions au temps ${fmtTime(currentTime)}`}
        style={{
          width: "100%",
          height: "auto",
          aspectRatio: "2 / 1",
          borderRadius: 4,
          background: "#0f0f1a",
        }}
      />

      {/* ---- controls ---- */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <button
          onClick={() => setPlaying((p) => !p)}
          aria-label={playing ? "Pause" : "Lecture"}
          style={{
            padding: "4px 12px",
            border: "1px solid var(--border)",
            borderRadius: 4,
            background: "var(--surface)",
            color: "var(--foreground)",
            cursor: "pointer",
            fontSize: 14,
            fontFamily: "var(--font-geist-sans, sans-serif)",
          }}
        >
          {playing ? "⏸ Pause" : "▶ Lecture"}
        </button>

        <input
          type="range"
          min={0}
          max={durationMs}
          step={100}
          value={currentTime}
          onChange={(e) => setCurrentTime(Number(e.target.value))}
          aria-label="Curseur temporel"
          style={{ flex: 1, minWidth: 120 }}
        />

        <span
          style={{
            fontSize: 13,
            color: "var(--muted-foreground)",
            fontVariantNumeric: "tabular-nums",
            minWidth: 60,
            textAlign: "right",
          }}
        >
          {fmtTime(currentTime)} / {fmtTime(durationMs)}
        </span>
      </div>

      {/* ---- legend ---- */}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "4px 12px",
          fontSize: 12,
          color: "var(--muted-foreground)",
        }}
      >
        {Object.entries(PROFESSION_COLORS).map(([prof, color]) => (
          <span
            key={prof}
            style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
          >
            <span
              style={{
                display: "inline-block",
                width: 10,
                height: 10,
                borderRadius: "50%",
                background: color,
              }}
            />
            {prof.substring(0, 4)}
          </span>
        ))}
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            marginLeft: 8,
          }}
        >
          <span
            style={{
              display: "inline-block",
              width: 10,
              height: 10,
              borderRadius: "50%",
              border: `1px solid ${COM_COLOR}`,
              background: "transparent",
              transform: "rotate(45deg)",
            }}
          />
          COM
        </span>
      </div>
    </section>
  );
}
