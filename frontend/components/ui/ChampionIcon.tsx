"use client";
/* eslint-disable @next/next/no-img-element */

import { useState } from "react";
import { championIcon } from "@/lib/icons";

/** Square champion portrait from Data Dragon, with a lettered tile if the icon is missing
 *  (e.g. a champion newer than the pinned Data Dragon version). */
export function ChampionIcon({
  name,
  size,
  className = "",
  ring,
}: {
  name: string;
  size: number;
  className?: string;
  ring?: string; // outline colour
}) {
  const [broken, setBroken] = useState(false);
  const style = {
    width: size,
    height: size,
    boxShadow: ring ? `0 0 0 1px ${ring}` : undefined,
  };
  if (broken) {
    return (
      <span
        className={`inline-flex shrink-0 items-center justify-center bg-bg-rail font-serif font-bold text-gold ${className}`}
        style={{ ...style, fontSize: size * 0.45 }}
        title={name}
        aria-label={name}
      >
        {name[0]?.toUpperCase()}
      </span>
    );
  }
  return (
    <img
      src={championIcon(name)}
      alt={name}
      title={name}
      width={size}
      height={size}
      loading="lazy"
      crossOrigin="anonymous"
      onError={() => setBroken(true)}
      className={`shrink-0 object-cover ${className}`}
      style={style}
    />
  );
}
