"use client";

import type { IndexRow } from "@/lib/types";
import { useT } from "@/lib/i18n";

// Hall of Legends crown -- a small gold inline icon rendered inline with the
// player's name.  Tooltip shows induction year when known.
export function HolCrown({ year }: { year: number | null }) {
  const title = useT().status.hol(year);
  return (
    <span
      title={title}
      aria-label={title}
      className="ml-1 inline-flex items-center text-accent-gold"
    >
      {/* crown / laurel glyph */}
      <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" aria-hidden>
        <path d="M12 3l2.8 4.5L20 9l-3.6 3.5L17.6 18 12 15.3 6.4 18l1.2-5.5L4 9l5.2-1.5L12 3z" />
      </svg>
    </span>
  );
}

// Status dot -- small colored circle instead of the old "Active"/"Retired"
// text chip. Green = currently competing; muted gray = retired;
// yellow = gray zone (hiatus / military / coaching / unknown).
export function StatusDot({ row }: { row: Pick<IndexRow, "is_active" | "is_retired"> }) {
  const m = useT();
  if (row.is_active === true) {
    return (
      <span
        title={m.status.active}
        aria-label={m.status.activeShort}
        className="inline-block h-2 w-2 shrink-0 rounded-full bg-emerald-400 ring-2 ring-emerald-400/20"
      />
    );
  }
  if (row.is_retired === true) {
    return (
      <span
        title={m.status.retired}
        aria-label={m.status.retired}
        className="inline-block h-2 w-2 shrink-0 rounded-full bg-text-dim/60"
      />
    );
  }
  return (
    <span
      title={m.status.inactive}
      aria-label={m.status.inactiveShort}
      className="inline-block h-2 w-2 shrink-0 rounded-full bg-amber-400 ring-2 ring-amber-400/20"
    />
  );
}
