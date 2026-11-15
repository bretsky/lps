"""
One-off: download the official event + league marks the site uses and normalize them
into square, trimmed PNGs under frontend/public/icons/{events,leagues}/<key>.png.

Sources: the LoL Esports CDN (static.lolesports.com) for the current marks,
Leaguepedia files for First Stand and the leagues the CDN doesn't serve, and Wikimedia
Commons for the Esports World Cup's "EWC" monogram plate (Leaguepedia only has its
two-line wordmark, which is illegible at badge size). Wordmark-style
logos are cropped to their emblem (`crop` = fraction of the trimmed width to keep, from
the left) so they read at 16-24px. Re-run only when a mark changes; the PNGs are committed.

    cd backend && python analysis/fetch_brand_icons.py          # needs Pillow (not a project dep)
    cd backend && python analysis/fetch_brand_icons.py ewc      # rebuild only the named keys
"""

from __future__ import annotations

import io
import json
import urllib.parse
import urllib.request
import sys
from pathlib import Path

from PIL import Image

OUT = Path(__file__).resolve().parents[2] / "frontend" / "public" / "icons"
UA = {"User-Agent": "LPS-bot/1.0 (league-performance-score)"}
CDN = "https://static.lolesports.com/leagues/"
SIZE = 128

# key -> (source, crop-from-left fraction or None)
EVENTS = {
    "worlds": (CDN + "1592594612171_WorldsDarkBG.png", None),
    "msi": (CDN + "1592594634248_MSIDarkBG.png", None),
    "first-stand": ("lp:First Stand logo.png", None),  # crest is cropped below (top band)
    # EWC Foundation logo: the solid "EWC" plate on its left is cut out below.
    "ewc": ("https://upload.wikimedia.org/wikipedia/commons/7/72/"
            "Esports_World_Cup_Foundation_%28EWCF%29._Svg.png", None),
}
LEAGUES = {
    "lck": (CDN + "lck-color-on-black.png", None),
    "lpl": (CDN + "1592516115322_LPL-01-FullonDark.png", None),
    "lec": (CDN + "1592516184297_LEC-01-FullonDark.png", None),
    "lcs": (CDN + "LCSNew-01-FullonDark.png", None),
    "cblol": (CDN + "cblol-logo-symbol-offwhite.png", None),
    "eu-lcs": ("lp:LCS Europe Logo.png", None),
    "na-lcs": ("lp:LCS NorthAmerica Logo.png", None),
    "lms": ("lp:LMS logo.png", None),
    "opl": ("lp:OPL logo.png", None),
    "tcl": ("lp:TCL logo.png", None),
    "lta": ("lp:LTA logo.png", 0.5),
    "lta-n": ("lp:LTA North logo.png", 0.42),
    "lta-s": ("lp:LTA South logo.png", 0.42),
    "lcp": ("lp:LCP Logo.png", 0.105),
    "lco": ("lp:LCO logo.png", 0.36),
    "pcs": ("lp:PCS logo full.png", 0.24),
}


def _get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read()


def _lp_url(file: str) -> str:
    q = urllib.parse.urlencode({"action": "query", "format": "json", "prop": "imageinfo",
                                "iiprop": "url", "iiurlwidth": 600, "titles": f"File:{file}"})
    d = json.loads(_get(f"https://lol.fandom.com/api.php?{q}"))
    page = next(iter(d["query"]["pages"].values()))
    return page["imageinfo"][0]["thumburl"]


def _trim(im: Image.Image) -> Image.Image:
    bbox = im.getchannel("A").point(lambda a: 255 if a > 24 else 0).getbbox()
    return im.crop(bbox) if bbox else im


def _square(im: Image.Image) -> Image.Image:
    im.thumbnail((SIZE, SIZE), Image.LANCZOS)
    canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    canvas.paste(im, ((SIZE - im.width) // 2, (SIZE - im.height) // 2), im)
    return canvas


def _ewc_plate(im: Image.Image) -> Image.Image:
    """The black "EWC" plate (letters knocked out) at the left of the EWC Foundation logo,
    found as the first solid run of a row through its upper half."""
    a = im.getchannel("A")
    y = im.height // 3
    x0 = next(x for x in range(im.width) if a.getpixel((x, y)) > 128)
    x1 = x0
    while x1 + 1 < im.width and a.getpixel((x1 + 1, y)) > 128:
        x1 += 1
    col = [yy for yy in range(im.height) if a.getpixel((x0 + 2, yy)) > 128]
    return im.crop((x0, col[0], x1 + 1, col[-1] + 1))


def build(key: str, src: str, crop: float | None, folder: str) -> None:
    url = _lp_url(src[3:]) if src.startswith("lp:") else src
    im = Image.open(io.BytesIO(_get(url))).convert("RGBA")
    if key == "ewc":
        im = _ewc_plate(im)
    im = _trim(im)
    if crop:
        im = _trim(im.crop((0, 0, int(im.width * crop), im.height)))
    if key == "first-stand":  # keep just the crest above the wordmark
        im = _trim(im.crop((0, 0, im.width, int(im.height * 0.2))))
    out = OUT / folder / f"{key}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    _square(im).save(out, optimize=True)
    print(f"{folder}/{key}.png  <- {src}")


def main() -> None:
    only = set(sys.argv[1:])
    for folder, marks in (("events", EVENTS), ("leagues", LEAGUES)):
        for key, (src, crop) in marks.items():
            if not only or key in only:
                build(key, src, crop, folder)


if __name__ == "__main__":
    main()
