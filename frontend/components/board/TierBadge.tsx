import type { TierKey } from "@/lib/types";
import { TIER_COLORS, TIER_LABELS } from "@/lib/theme";

/** Engraved tier plaque: lozenge + caps in the tier's colour, chamfered edge. */
export function TierBadge({ tier, size = "sm" }: { tier: TierKey; size?: "sm" | "md" }) {
  const c = TIER_COLORS[tier];
  const md = size === "md";
  return (
    <span
      className={`inline-flex items-center gap-1.5 font-serif font-bold uppercase ${
        md ? "px-2.5 py-1 text-[11px] tracking-[0.22em]" : "px-1.5 py-0.5 text-[9px] tracking-[0.18em]"
      }`}
      style={{
        color: c,
        background: `linear-gradient(90deg, ${c}26, ${c}0d)`,
        boxShadow: `inset 0 0 0 1px ${c}66`,
        clipPath: "polygon(5px 0, 100% 0, 100% calc(100% - 5px), calc(100% - 5px) 100%, 0 100%, 0 5px)",
      }}
    >
      <span className={`${md ? "h-1.5 w-1.5" : "h-1 w-1"} rotate-45`} style={{ background: c }} />
      {TIER_LABELS[tier]}
    </span>
  );
}
