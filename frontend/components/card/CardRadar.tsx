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
const CY = 120;
const R = 78;
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
        height="222"
        viewBox="0 0 256 222"
        className="overflow-visible"
      >
        {/* grid rings */}
        {[0.25, 0.5, 0.75, 1.0].map((frac) => (
          <polygon
            key={frac}
            points={gridPolygon(frac)}
            fill="none"
            stroke="#1e2a38"
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
              stroke="#1e2a38"
              strokeWidth={0.75}
            />
          );
        })}
        {/* player polygon */}
        <polygon
          points={polygonPoints(values)}
          fill={`${accentColor}1a`}
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
                fontSize="8"
                fontFamily="ui-sans-serif, system-ui, sans-serif"
                fill="#5c6675"
              >
                {axis.label}
              </text>
              <text
                x={lx.toFixed(1)}
                y={(ly + 8).toFixed(1)}
                textAnchor={anchor}
                fontSize="8.5"
                fontFamily="ui-monospace, Consolas, monospace"
                fontWeight={bright ? "600" : "400"}
                fill={bright ? accentColor : "#8a94a3"}
              >
                {pct != null ? Math.round(pct) : "—"}
              </text>
            </g>
          );
        })}
      </svg>

      {/* global / lane toggle */}
      <div className="mt-1.5 flex items-center rounded-full border border-border bg-bg-rail p-0.5">
        {(["global", "lane"] as const).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            disabled={m === "lane" && !hasLane}
            className={`rounded-full px-2.5 py-0.5 text-[9px] font-medium uppercase tracking-wide transition-colors ${
              mode === m
                ? "bg-bg-card text-text"
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
