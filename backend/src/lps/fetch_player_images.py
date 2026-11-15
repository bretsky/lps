"""
Fetch a player photo per workbook player from Leaguepedia and cache the CDN URLs.

Writes:
  data/leaguepedia/player_images.json
      {label: {url, file, team, tournament, year, page, real_name, country} | null}

How it works (same image source as the pickems dashboard, but via Cargo so it can
batch thousands of players and date every photo):

  1. Bare handle per workbook label ("Knight (LPL)" -> "Knight", "Faker #2" -> "Faker").
  2. Candidate Leaguepedia pages per handle from `Players.ID` (catches every
     disambiguated page like "Knight (Zhuo Ding)") and `PlayerRedirects.AllName`
     (catches renamed players and redirects like "Uzi" -> "Uzi (Jian Zi-Hao)").
  3. Every photo on those pages from `PlayerImages`, joined to `Tournaments` for a
     date. Each photo is captioned with a team + tournament.
  4. Pages are matched to labels by roster vote: a photo of handle H on team T in year
     Y votes for the Oracle player who played as H on T in Y (`player_identity`'s
     team-year bridge). That separates the LPL Knight from the VCS Knight. A handle
     with a single label and no votes falls back to its only / un-suffixed page.
  5. Newest photo per matched page taken during the player's career (First..Last in the
     workbook) so retired players show a playing-days photo, not a later appearance;
     All-Star costume shots lose ties within a year. Resolved to a scaled CDN thumbnail
     via the MediaWiki imageinfo API.
  6. The matched page's `Players.Name` / `Country` ride along for the card's name block.

`info/player_image_overrides.csv` (label,file) pins a specific wiki file when the
guess is wrong; an empty `file` blocks a photo for that label.

Run:
    poetry run python -m lps.fetch_player_images            # incremental (new labels only)
    poetry run python -m lps.fetch_player_images --refresh  # re-pick every photo
    poetry run python -m lps.fetch_player_images --players Faker "Knight (LPL)"
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass

from .config import INFO_DIR, LEAGUEPEDIA_DIR
from .lp_client import LPClient

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

PLAYER_IMAGES_JSON = LEAGUEPEDIA_DIR / "player_images.json"
OVERRIDES_CSV = INFO_DIR / "player_image_overrides.csv"

_BATCH = 80          # names per Cargo IN() query
_IMG_BATCH = 50      # MediaWiki imageinfo titles per request
_THUMB_WIDTH = 640   # px; cards render ~300 css px wide, so this covers 2x DPR
_MW_API = "https://lol.fandom.com/api.php"
_MW_UA = "LPS-bot/1.0 (league-performance-score)"

_SUFFIX_RE = re.compile(r"\s*(#\d+|\([^)]*\))\s*$")
_YEAR_RE = re.compile(r"(20\d\d)")


@dataclass
class _Photo:
    file: str
    page: str
    team: str
    tournament: str
    date: str   # ISO yyyy-mm-dd, or "" when unknown
    year: int | None

    @property
    def allstar(self) -> bool:
        t = self.tournament.lower()
        return "all-star" in t or "all star" in t or "allstar" in t

    def sort_key(self) -> tuple:
        return (self.year or 0, not self.allstar, self.date)


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def bare_handle(label: str) -> str:
    """'Knight (LPL)' -> 'Knight'; 'Faker #2' -> 'Faker'; 'Faker' -> 'Faker'."""
    prev = None
    while prev != label:
        prev, label = label, _SUFFIX_RE.sub("", label)
    return label.strip()


def _in_batches(values: list[str]):
    for i in range(0, len(values), _BATCH):
        batch = values[i : i + _BATCH]
        yield ", ".join(f'"{_escape(v)}"' for v in batch)


def _candidate_pages(handles: list[str], lp: LPClient) -> dict[str, set[str]]:
    """{handle_lower: {Leaguepedia page, ...}} from Players.ID and PlayerRedirects.AllName.

    Cargo's collation is accent/case-insensitive ("Viper" also hits "Vipér"), so keep only
    exact casefold matches.
    """
    out: dict[str, set[str]] = defaultdict(set)
    for quoted in _in_batches(handles):
        for r in lp.query(tables="Players", fields="ID=id, OverviewPage=page",
                          where=f"ID IN ({quoted})"):
            if r.get("id") and r.get("page"):
                out[r["id"].casefold()].add(r["page"])
        for r in lp.query(tables="PlayerRedirects", fields="AllName=name, OverviewPage=page",
                          where=f"AllName IN ({quoted})"):
            if r.get("name") and r.get("page"):
                out[r["name"].casefold()].add(r["page"])
        time.sleep(1)
    wanted = {h.casefold() for h in handles}
    return {h: pages for h, pages in out.items() if h in wanted}


def _page_photos(pages: list[str], lp: LPClient) -> dict[str, list[_Photo]]:
    """{page_casefold: [photo, ...]} for every PlayerImages row on those pages."""
    out: dict[str, list[_Photo]] = defaultdict(list)
    for quoted in _in_batches(pages):
        rows = lp.query(
            tables="PlayerImages=PI, Tournaments=T",
            join_on="PI.Tournament=T.OverviewPage",
            fields=("PI.FileName=file, PI.Link=link, PI.Team=team, PI.Tournament=tourn, "
                    "PI.SortDate=sortdate, T.DateStart=start, T.Year=year"),
            where=f"PI.Link IN ({quoted})",
        )
        for r in rows:
            file, link = (r.get("file") or "").strip(), (r.get("link") or "").strip()
            if not file or not link or not file.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                continue
            date = (r.get("start") or r.get("sortdate") or "").strip()
            year = None
            for src in (r.get("year"), date, r.get("tourn"), file):
                m = _YEAR_RE.search(str(src or ""))
                if m:
                    year = int(m.group(1))
                    break
            out[link.casefold()].append(_Photo(
                file=file, page=link, team=(r.get("team") or "").strip(),
                tournament=(r.get("tourn") or "").strip(), date=date, year=year,
            ))
        time.sleep(1)
    return out


def _match_pages(
    labels: list[str],
    pages_by_handle: dict[str, set[str]],
    photos_by_page: dict[str, list[_Photo]],
) -> dict[str, str]:
    """{label: page} via roster votes (see module docstring, step 4)."""
    from .player_identity import _identity, _team_key

    ident = _identity()
    pid_by_hty: dict = ident.get("pid_by_hty", {})
    label_by_pid: dict = ident["label_by_pid"]

    labels_by_handle: dict[str, list[str]] = defaultdict(list)
    for lab in labels:
        labels_by_handle[bare_handle(lab).casefold()].append(lab)

    out: dict[str, str] = {}
    for h, labs in labels_by_handle.items():
        pages = sorted(p for p in pages_by_handle.get(h, ()) if photos_by_page.get(p.casefold()))
        if not pages:
            continue
        labset = set(labs)
        votes: dict[tuple[str, str], int] = defaultdict(int)  # (label, page) -> n
        for p in pages:
            for ph in photos_by_page[p.casefold()]:
                if ph.year is None:
                    continue
                pid = pid_by_hty.get((h, _team_key(ph.team), ph.year))
                lab = label_by_pid.get(pid) if pid else None
                if lab in labset:
                    votes[(lab, p)] += 1
        # Greedy: strongest (label, page) pairs first, one page per label and vice versa.
        used_pages: set[str] = set()
        for (lab, p), _n in sorted(votes.items(), key=lambda kv: -kv[1]):
            if lab in out or p in used_pages:
                continue
            out[lab] = p
            used_pages.add(p)
        # Fallback for a handle owned by one player whose photos predate Oracle rosters.
        unmatched = [lab for lab in labs if lab not in out]
        if len(labs) == 1 and unmatched:
            free = [p for p in pages if p not in used_pages]
            exact = [p for p in free if p.casefold() == h]
            if len(free) == 1:
                out[labs[0]] = free[0]
            elif exact:
                out[labs[0]] = exact[0]
    return out


def _page_bios(pages: list[str], lp: LPClient) -> dict[str, dict[str, str]]:
    """{page_casefold: {real_name, country}} from the Players table."""
    out: dict[str, dict[str, str]] = {}
    for quoted in _in_batches(pages):
        for r in lp.query(tables="Players", fields="OverviewPage=page, Name=name, Country=country",
                          where=f"OverviewPage IN ({quoted})"):
            if r.get("page"):
                out[r["page"].casefold()] = {"real_name": (r.get("name") or "").strip(),
                                             "country": (r.get("country") or "").strip()}
        time.sleep(1)
    return out


def _thumb_urls(files: list[str], width: int = _THUMB_WIDTH) -> dict[str, str]:
    """{file: scaled CDN thumbnail url} via the MediaWiki imageinfo API."""
    out: dict[str, str] = {}
    for i in range(0, len(files), _IMG_BATCH):
        chunk = files[i : i + _IMG_BATCH]
        params = urllib.parse.urlencode({
            "action": "query", "format": "json", "prop": "imageinfo",
            "iiprop": "url", "iiurlwidth": width,
            "titles": "|".join(f"File:{f}" for f in chunk),
        })
        req = urllib.request.Request(f"{_MW_API}?{params}", headers={"User-Agent": _MW_UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 -- a missing photo is fine
            logger.warning("[images] imageinfo error for batch %d: %s", i, exc)
            time.sleep(2)
            continue
        q = data.get("query", {})
        # Titles come back normalized ("A_b.png" -> "A b.png"); map back to what we sent.
        norm = {n["to"]: n["from"] for n in q.get("normalized", [])}
        for page in q.get("pages", {}).values():
            info = page.get("imageinfo") or []
            if not info:
                continue
            url = info[0].get("thumburl") or info[0].get("url")
            title = norm.get(page.get("title", ""), page.get("title", ""))
            if url and title.startswith("File:"):
                out[title[len("File:"):]] = url
        time.sleep(0.5)
    return out


def _load_overrides() -> dict[str, str]:
    if not OVERRIDES_CSV.exists():
        return {}
    with OVERRIDES_CSV.open(encoding="utf-8", newline="") as f:
        return {r["label"].strip(): (r.get("file") or "").strip()
                for r in csv.DictReader(f) if (r.get("label") or "").strip()}


def _pick(photos: list[_Photo], career: tuple[int, int] | None) -> _Photo:
    if career:
        first, last = career
        during = [ph for ph in photos if ph.year is not None and first <= ph.year <= last]
        if during:
            return max(during, key=_Photo.sort_key)
    return max(photos, key=_Photo.sort_key)


def workbook_players() -> dict[str, tuple[int, int] | None]:
    """{label: (first_year, last_year)} from the Overview sheet of the career workbook."""
    import openpyxl

    from .export_web import _latest_career_workbook

    path = _latest_career_workbook()
    logger.info("[images] reading players from %s", path.name)
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    rows = wb["Overview"].iter_rows(values_only=True)
    headers = [str(h).strip() if h is not None else "" for h in next(rows)]
    name_i = next(headers.index(c) for c in ("Player", "playername", "player") if c in headers)
    first_i = headers.index("First") if "First" in headers else None
    last_i = headers.index("Last") if "Last" in headers else None
    out: dict[str, tuple[int, int] | None] = {}
    for r in rows:
        if not r[name_i]:
            continue
        span = None
        if first_i is not None and last_i is not None and r[first_i] and r[last_i]:
            span = (int(r[first_i]), int(r[last_i]))
        out[str(r[name_i]).strip()] = span
    wb.close()
    return out


def fetch_player_images(
    labels: list[str],
    lp: LPClient,
    careers: dict[str, tuple[int, int] | None] | None = None,
) -> dict[str, dict | None]:
    """{label: {url, file, team, tournament, year, page, real_name, country} | None}.

    `careers` ({label: (first_year, last_year)}) steers each pick toward a photo from the
    player's playing years.
    """
    careers = careers or {}
    overrides = _load_overrides()
    auto = [lab for lab in labels if lab not in overrides]

    handles = sorted({bare_handle(lab) for lab in auto})
    logger.info("[images] %d labels -> %d handles; looking up Leaguepedia pages", len(auto), len(handles))
    pages_by_handle = _candidate_pages(handles, lp)
    all_pages = sorted({p for ps in pages_by_handle.values() for p in ps})
    logger.info("[images] %d candidate pages; fetching photo lists", len(all_pages))
    photos_by_page = _page_photos(all_pages, lp)
    page_by_label = _match_pages(auto, pages_by_handle, photos_by_page)
    logger.info("[images] matched %d/%d labels to a page with photos", len(page_by_label), len(auto))

    chosen: dict[str, _Photo] = {}
    for lab, page in page_by_label.items():
        chosen[lab] = _pick(photos_by_page[page.casefold()], careers.get(lab))
    for lab, file in overrides.items():
        if lab in labels and file:
            chosen[lab] = _Photo(file=file, page="", team="", tournament="", date="",
                                 year=(int(m.group(1)) if (m := _YEAR_RE.search(file)) else None))

    bios = _page_bios(sorted(set(page_by_label.values())), lp)
    urls = _thumb_urls(sorted({ph.file for ph in chosen.values()}))
    out: dict[str, dict | None] = {}
    for lab in labels:
        ph = chosen.get(lab)
        page = page_by_label.get(lab)
        bio = bios.get(page.casefold(), {}) if page else {}
        if ph and ph.file in urls:
            out[lab] = {"url": urls[ph.file], "file": ph.file, "team": ph.team or None,
                        "tournament": ph.tournament or None, "year": ph.year,
                        "page": page, "real_name": bio.get("real_name") or None,
                        "country": bio.get("country") or None}
        else:
            out[lab] = None
    logger.info("[images] resolved %d/%d photos", sum(v is not None for v in out.values()), len(labels))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--players", nargs="+", metavar="LABEL", help="Specific workbook labels (default: all).")
    parser.add_argument("--refresh", action="store_true", help="Re-pick photos for labels already cached.")
    args = parser.parse_args()

    cache: dict[str, dict | None] = {}
    if PLAYER_IMAGES_JSON.exists():
        cache = json.loads(PLAYER_IMAGES_JSON.read_text(encoding="utf-8"))
        logger.info("[images] loaded %d cached entries", len(cache))

    careers = workbook_players()
    labels = args.players or list(careers)
    if not (args.refresh or args.players):
        labels = [lab for lab in labels if lab not in cache]
    if not labels:
        logger.info("[images] nothing to fetch (use --refresh to re-pick)")
        return

    cache.update(fetch_player_images(labels, LPClient(), careers))
    LEAGUEPEDIA_DIR.mkdir(parents=True, exist_ok=True)
    PLAYER_IMAGES_JSON.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    logger.info("[images] wrote %s", PLAYER_IMAGES_JSON)


if __name__ == "__main__":
    main()
