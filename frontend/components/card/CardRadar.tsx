"use client";

import { useState } from "react";
import type { PlayerDetail, RadarAxes } from "@/lib/types";
import { laneLabel } from "@/lib/format";

const AXES: { key: RadarAxes; label: string }[] = [
  { key: "peak", label: "Peak" },
  { key: "longevity", label: "Longev." },
  { key: "consistency", label: "Consis." },
  { key: "resume", label: "Résumé" },
  { key: "impact", label: "Impact" },
  { key: "clutch", label: "Clutch" },
  { key: "dominance", label: "Domin." },
];

const N = AXES.length;
const CX = 128;
const CY = 116;
const R = 76;
const LABEL_R = R + 18;

function axisAngle(i: number): number {
  return (i / N) * 2 * Math.PI - Math.PI / 2;
}

function polarXY(r: number, angle: number): [number, number] {
  return [CX + r * Math.cos(angle), CY + r * Math.sin(angle)];
}

function polygonPoints(values: (number | null)[]): string {
  return values
    .map((v, i) => {
      const [x, y] = polarXY(((v ?? 0) / 100) * R, axisAngle(i));
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

function gridPolygon(frac: number): string {
  return Array.from({ length: N }, (_, i) => {
    const [x, y] = polarXY(frac * R, axisAngle(i));
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
}

interface CardRadarProps {
  player: PlayerDetail;
  accentColor: string;
}

export function CardRadar({ player, accentColor }: CardRadarProps) {
  const hasLane = player.radar.lane !== null;
  const [mode, setMode] = useState<"global" | "lane">("global");
  const radarData = mode === "lane" && hasLane ? player.radar.lane! : player.radar.global;
  const values = AXES.map((a) => radarData[a.key] ?? null);

  return (
    <div className="flex flex-col items-center">
      {/* SVG radar chart */}
      <svg
        width="256"
        height="212"
        viewBox="0 0 256 212"
        className="overflow-visible"
      >
        {/* grid rings */}
        {[0.25, 0.5, 0.75, 1.0].map((frac) => (
          <polygon
            key={frac}
            points={gridPolygon(frac)}
            fill="none"
            stroke="rgba(77,163,255,0.22)"
            strokeWidth={frac === 1.0 ? 1.5 : 0.75}
          />
        ))}
        {/* axes */}
        {AXES.map((_, i) => {
          const [x2, y2] = polarXY(R, axisAngle(i));
          return (
            <line
              key={i}
              x1={CX}
              y1={CY}
              x2={x2.toFixed(1)}
              y2={y2.toFixed(1)}
              stroke="rgba(77,163,255,0.22)"
              strokeWidth={0.75}
            />
          );
        })}
        {/* player polygon */}
        <polygon
          points={polygonPoints(values)}
          fill={`${accentColor}2e`}
          style={{ filter: `drop-shadow(0 0 6px ${accentColor}aa)` }}
          stroke={accentColor}
          strokeWidth={1.5}
          strokeLinejoin="round"
        />
        {/* dots */}
        {values.map((v, i) => {
          const [x, y] = polarXY(((v ?? 0) / 100) * R, axisAngle(i));
          return (
            <circle
              key={i}
              cx={x.toFixed(1)}
              cy={y.toFixed(1)}
              r={2.5}
              fill={accentColor}
            />
          );
        })}
        {/* axis labels */}
        {AXES.map((axis, i) => {
          const a = axisAngle(i);
          const [lx, ly] = polarXY(LABEL_R, a);
          const pct = values[i];
          const anchor = lx < CX - 4 ? "end" : lx > CX + 4 ? "start" : "middle";
          const bright = pct != null && pct >= 90;
          return (
            <g key={axis.key}>
              <text
                x={lx.toFixed(1)}
                y={(ly - 3).toFixed(1)}
                textAnchor={anchor}
                fontSize="9"
                fontFamily="var(--font-display), sans-serif" fontStyle="italic" fontWeight="600" letterSpacing="0.06em"
                fill="#7f93bd"
              >
                {axis.label}
              </text>
              <text
                x={lx.toFixed(1)}
                y={(ly + 8).toFixed(1)}
                textAnchor={anchor}
                fontSize="8.5"
                fontFamily="var(--font-mono), monospace"
                fontWeight={bright ? "600" : "400"}
                fill={bright ? accentColor : "#c9d6f2"}
              >
                {pct != null ? Math.round(pct) : "—"}
              </text>
            </g>
          );
        })}
      </svg>

      {/* global / lane toggle */}
      <div className="mt-1.5 deco-control flex items-center p-0.5">
        {(["global", "lane"] as const).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            disabled={m === "lane" && !hasLane}
            className={`px-2.5 py-0.5 font-display text-[10px] font-semibold uppercase italic tracking-wider transition-colors ${
              mode === m
                ? "bg-accent-hex/20 text-accent-cyan"
                : "text-text-dim hover:text-text-muted disabled:cursor-not-allowed disabled:opacity-25"
            }`}
          >
            {m === "global" ? "All players" : `vs ${laneLabel(player.position)}`}
          </button>
        ))}
      </div>
    </div>
  );
}
