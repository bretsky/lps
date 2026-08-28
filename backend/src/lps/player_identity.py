"""Canonical player identity -- disambiguate shared handles via Oracle's stable playerid.

Oracle's Elixir keys every row by both a display handle (`playername`, which COLLIDES --
e.g. three different people have played as "Knight" in LPL, VCS and NA LCS) and a stable
unique id (`playerid`, an `oe:player:...` hash). The scoring pipeline groups on the handle,
which silently merges those distinct people into one.

This module builds, from all Oracle years, a globally-unique **display label** per playerid:
  * a handle owned by exactly one playerid keeps its canonical casing verbatim ("Faker");
  * a colliding handle is qualified by that player's primary (most-played) league, e.g.
    "Knight", "Knight (VCS)", "Knight (NA LCS)" -- and a "#n" suffix as a last-resort
    tiebreak so labels are always unique.

Callers replace `playername` with this label at the point names attach to the scored frames
(`season._player_lane_table`, `lp_reduced`), so every downstream groupby keeps working while
now separating the real people. The label is STABLE across years (keyed on playerid), so
cross-year career aggregation stays correct too.

For data that only has a handle (pre-2014 Leaguepedia, or Leaguepedia-sourced achievements),
`resolve_label(handle, region)` bridges to a playerid -- by (handle, league) when the handle
collides, else by a globally-unique handle -- and returns the same label; unbridged handles
(genuinely Leaguepedia-only players) fall through to the raw handle.
"""

from __future__ import annotations

import functools
import logging
import pickle

import pandas as pd

from .config import DATA_DIR
from .io_oracle import list_oracle_files

logger = logging.getLogger(__name__)

_CACHE = DATA_DIR / "cache" / "player_identity.pkl"
_ID_COLS = ("playername", "playerid", "league", "position")


def _mode(s: pd.Series) -> str:
    """Most common value (ties broken by first-seen via value_counts ordering)."""
    return s.value_counts().idxmax()


def _read_identity_rows() -> pd.DataFrame:
    frames = []
    for p in list_oracle_files():
        try:
            df = pd.read_csv(p, usecols=lambda c: c in _ID_COLS, low_memory=False)
        except ValueError:  # a year missing one of the columns
            df = pd.read_csv(p, low_memory=False)
            df = df[[c for c in _ID_COLS if c in df.columns]]
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["playername", "playerid", "league"])
    d = pd.concat(frames, ignore_index=True)
    if "position" in d.columns:
        d = d[d["position"].astype(str).str.lower() != "team"]
    d = d.dropna(subset=["playername", "playerid"]).copy()
    d["playername"] = d["playername"].astype(str).str.strip()
    d["playerid"] = d["playerid"].astype(str).str.strip()
    d = d[(d["playername"] != "") & (d["playerid"] != "")]
    d["league"] = d.get("league", "").astype(str).str.strip() if "league" in d.columns else ""
    return d


def _build() -> dict:
    d = _read_identity_rows()
    if d.empty:
        return {"label_by_pid": {}, "pid_by_hr": {}, "pid_by_h": {}}

    handle = d.groupby("playerid")["playername"].agg(_mode)  # canonical casing per person
    primary = d.groupby("playerid")["league"].agg(_mode)  # most-played league per person
    hl_counts = handle.str.lower().value_counts()  # handle -> #distinct people

    label_by_pid: dict[str, str] = {}
    used: set[str] = set()
    for pid, h in handle.items():
        if hl_counts[h.lower()] > 1:  # collision -> qualify by primary league
            reg = primary.get(pid, "") or ""
            label = f"{h} ({reg})" if reg else h
        else:
            label = h
        base, k = label, 2
        while label.lower() in used:  # guarantee global uniqueness
            label = f"{base} #{k}"
            k += 1
        used.add(label.lower())
        label_by_pid[pid] = label

    hlow = d["playername"].str.lower()
    # (handle, league) -> playerid, only where that pair is unambiguous.
    hr_n = d.groupby([hlow, d["league"]])["playerid"].nunique()
    hr_mode = d.groupby([hlow, d["league"]])["playerid"].agg(_mode)
    pid_by_hr = {k: v for k, v in hr_mode.items() if hr_n[k] == 1}
    # handle -> playerid, only where the handle is globally unique.
    h_n = d.groupby(hlow)["playerid"].nunique()
    h_mode = d.groupby(hlow)["playerid"].agg(_mode)
    pid_by_h = {k: v for k, v in h_mode.items() if h_n[k] == 1}

    return {"label_by_pid": label_by_pid, "pid_by_hr": pid_by_hr, "pid_by_h": pid_by_h}


@functools.lru_cache(maxsize=1)
def _identity() -> dict:
    files = list_oracle_files()
    mtime = max((f.stat().st_mtime for f in files), default=0.0)
    if _CACHE.exists():
        try:
            obj = pickle.loads(_CACHE.read_bytes())
            if obj.get("_mtime") == mtime:
                return obj
        except Exception:  # corrupt/old cache -> rebuild
            pass
    obj = _build()
    obj["_mtime"] = mtime
    try:
        _CACHE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE.write_bytes(pickle.dumps(obj))
    except Exception:
        logger.debug("[player_identity] could not write cache", exc_info=True)
    return obj


def label_map() -> dict[str, str]:
    """{playerid -> unique display label}."""
    return _identity()["label_by_pid"]


def resolve_label(handle: object, region: object = None) -> object:
    """Map a bare handle (+ optional league/region) to its canonical unique label.

    Bridges to a playerid by (handle, region) for colliding handles, else by a globally
    unique handle; returns the handle unchanged when it can't be bridged (Leaguepedia-only
    players). Region matching uses Oracle's `league` vocabulary (LPL, VCS, NA LCS, ...).
    """
    if handle is None or (isinstance(handle, float) and pd.isna(handle)):
        return handle
    obj = _identity()
    hl = str(handle).strip().lower()
    if not hl:
        return handle
    pid = None
    if region is not None and not (isinstance(region, float) and pd.isna(region)):
        pid = obj["pid_by_hr"].get((hl, str(region).strip()))
    if pid is None:
        pid = obj["pid_by_h"].get(hl)
    if pid is not None:
        return obj["label_by_pid"].get(pid, handle)
    return handle
