import type { TierKey } from "@/lib/types";

const LABELS: Record<TierKey, string> = {
  goats: "GOATs",
  legends: "Legends",
  greats: "Greats",
  elite: "Elite",
  stars: "Stars",
  contenders: "Contenders",
};

const CLASSES: Record<TierKey, string> = {
  goats: "bg-tier-goats/20 text-tier-goats border-tier-goats/40",
  legends: "bg-tier-legends/20 text-tier-legends border-tier-legends/40",
  greats: "bg-tier-greats/20 text-tier-greats border-tier-greats/40",
  elite: "bg-tier-elite/20 text-tier-elite border-tier-elite/40",
  stars: "bg-tier-stars/20 text-tier-stars border-tier-stars/40",
  contenders: "bg-tier-contenders/15 text-tier-contenders border-tier-contenders/30",
};

export function TierBadge({ tier, size = "sm" }: { tier: TierKey; size?: "sm" | "md" }) {
  const cls =
    size === "md"
      ? "px-2 py-0.5 text-xs font-semibold"
      : "px-1.5 py-0.5 text-[10px] font-semibold";
  return (
    <span
      className={`inline-flex items-center rounded border uppercase tracking-wide ${cls} ${CLASSES[tier]}`}
    >
      {LABELS[tier]}
    </span>
  );
}
