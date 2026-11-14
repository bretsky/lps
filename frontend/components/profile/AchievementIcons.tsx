// SVG silhouettes for the trajectory chart's achievement badges.
//
// Each *tournament family* has a distinct cup silhouette, and the medal tint
// (gold / silver / bronze) is applied by the parent via currentColor. Awards
// (MVP / All-Pro) get their own unique shapes plus their own tint families.
// All icons share a 24x24 viewBox and use fill=currentColor.

type IconProps = { className?: string; style?: React.CSSProperties };

// Summoner's Cup — the Worlds trophy. Wide-flanged crown of four curved
// blade-wings on a tapered chalice with a stepped base. Distinctive
// silhouette even at 20px.
export function CupWorlds({ className, style }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} style={style} fill="currentColor" aria-hidden>
      {/* Four blade-wings springing from the rim. Center pair straight, outer pair curling out. */}
      <path d="M11 8 L 10 2 L 12 6 L 14 2 L 13 8 Z" />
      <path d="M8 8 L 5 2 Q 6 5 7.5 7 L 6 3 L 8.5 6.5 Z" />
      <path d="M16 8 L 19 2 Q 18 5 16.5 7 L 18 3 L 15.5 6.5 Z" />
      {/* Cup bowl — tapered inward toward the stem */}
      <path d="M6 8 H 18 L 16 14 Q 16 15 12 15 Q 8 15 8 14 Z" />
      {/* Stem + wide plinth base */}
      <path d="M10.5 15 H 13.5 V 17.5 H 16.5 V 19 H 17.5 V 21 H 6.5 V 19 H 7.5 V 17.5 H 10.5 Z" />
    </svg>
  );
}

// MSI — round chalice with two prominent oval "ear" handles.
export function CupMsi({ className, style }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} style={style} fill="currentColor" aria-hidden>
      <path d="M6 6 Q 2.5 7 2.5 10.5 Q 2.5 14 6 14.5 V 12.5 Q 4.5 12.5 4.5 10.5 Q 4.5 8.5 6 8.5 Z" />
      <path d="M18 6 Q 21.5 7 21.5 10.5 Q 21.5 14 18 14.5 V 12.5 Q 19.5 12.5 19.5 10.5 Q 19.5 8.5 18 8.5 Z" />
      <path d="M6 5 H 18 V 12 Q 18 16 12 16 Q 6 16 6 12 Z" />
      <path d="M11 16 H 13 V 18.5 H 16.5 V 20.5 H 7.5 V 18.5 H 11 Z" />
    </svg>
  );
}

// Other international events — slim cup with a small pointed lid, small side handles.
export function CupIntl({ className, style }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} style={style} fill="currentColor" aria-hidden>
      <path d="M12 2 L 10 5 H 14 Z" />
      <path d="M9 5 H 15 V 7 H 9 Z" />
      <path d="M8 7 H 16 V 12 Q 16 15 12 15 Q 8 15 8 12 Z" />
      <path d="M8 8 H 6 Q 5 8 5 10 Q 5 12 6 12 H 8 V 11 H 6.5 V 9 H 8 Z" />
      <path d="M16 8 H 18 Q 19 8 19 10 Q 19 12 18 12 H 16 V 11 H 17.5 V 9 H 16 Z" />
      <path d="M11 15 H 13 V 17.5 H 16 V 19.5 H 8 V 17.5 H 11 Z" />
    </svg>
  );
}

// Domestic-league trophy — tall FIFA-style body with two large loop handles.
export function CupDomestic({ className, style }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} style={style} fill="currentColor" aria-hidden>
      <path d="M7 5 Q 3 5 3 9 Q 3 12 6.5 12.5 V 10.5 Q 5 10.5 5 9 Q 5 7 7 7 Z" />
      <path d="M17 5 Q 21 5 21 9 Q 21 12 17.5 12.5 V 10.5 Q 19 10.5 19 9 Q 19 7 17 7 Z" />
      <path d="M7 3 H 17 V 13 Q 17 15.5 12 15.5 Q 7 15.5 7 13 Z" />
      <path d="M11 15.5 H 13 V 18 H 16.5 V 20.5 H 7.5 V 18 H 11 Z" />
    </svg>
  );
}

// Domestic cup (KeSPA / Demacia / …) — laurel wreath around a central medal disc.
export function Laurel({ className, style }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} style={style} fill="currentColor" aria-hidden>
      {/* Left laurel */}
      <path d="M6 5 Q 3 8 4 12 Q 5 14 7 14 Q 7 11 6.5 9 Q 6.2 7 6 5 Z" />
      <path d="M4 9 Q 3 11 4.5 13 Q 5.5 12 5 10 Z" />
      <path d="M5 7 Q 4 8.5 5 10 Q 6 9 5.8 8 Z" />
      {/* Right laurel */}
      <path d="M18 5 Q 21 8 20 12 Q 19 14 17 14 Q 17 11 17.5 9 Q 17.8 7 18 5 Z" />
      <path d="M20 9 Q 21 11 19.5 13 Q 18.5 12 19 10 Z" />
      <path d="M19 7 Q 20 8.5 19 10 Q 18 9 18.2 8 Z" />
      {/* Center medal */}
      <circle cx="12" cy="11" r="3" />
      {/* Ribbon tails */}
      <path d="M9.5 14 L 10.5 18 L 12 17 L 13.5 18 L 14.5 14 Z" />
    </svg>
  );
}

// Star — MVP.
export function Star({ className, style }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} style={style} fill="currentColor" aria-hidden>
      <path d="M12 2 L 14.5 8.5 L 21.5 9 L 16 13.5 L 17.8 20.5 L 12 16.7 L 6.2 20.5 L 8 13.5 L 2.5 9 L 9.5 8.5 Z" />
    </svg>
  );
}

// Shield with an inset star — All-Pro selection.
export function Shield({ className, style }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} style={style} fill="currentColor" aria-hidden>
      <path d="M12 2 L 20 5 V 11 Q 20 17 12 22 Q 4 17 4 11 V 5 Z" />
      <path
        d="M12 7 L 13.4 10.2 L 16.8 10.4 L 14.1 12.5 L 15 15.8 L 12 13.9 L 9 15.8 L 9.9 12.5 L 7.2 10.4 L 10.6 10.2 Z"
        fill="#0a0e14"
      />
    </svg>
  );
}
