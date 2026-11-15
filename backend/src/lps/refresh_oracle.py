"""Refresh the Oracle's Elixir season CSVs in data/oracle/ from OE's public Drive folder.

Ported from draftpredict's ``scripts/refresh_oracle.py``. ``update_all`` runs it
first, so a rankings rebuild always starts from the newest box scores; it can
also be run by itself:

    poetry run python -m lps.refresh_oracle            # download what changed
    poetry run python -m lps.refresh_oracle --check    # report only
    poetry run python -m lps.refresh_oracle --only 2026

Downloads go through the Drive API as you, using python-sharp's OAuth token
(``token.json``, which already has the drive scope; ``PSHARP_PATH`` overrides
where python-sharp lives). Anonymous downloads (gdown, the browser link) often
hit Drive's "too many users have downloaded this file" quota because OE's files
are popular. If the API download hits that quota too, the file is copied into
your own Drive, the copy is downloaded and then deleted, since a copy has its
own fresh quota.

A file is fetched only when Drive's md5 differs from the local file's. Local
md5s are cached in ``data/cache/oracle_refresh.json`` so unchanged files aren't
re-hashed on every run. A download is swapped in only once it passes three
checks: its md5 matches Drive's, its header still has every column the old file
had, and its game count didn't drop. OE corrects old rows now and then but never
removes games; ``--force`` overrides the game-count check. The swap is an atomic
rename.

Unlike draftpredict, LPS derives its seasons from what's on disk
(``io_oracle.available_oracle_years``). So a season that appears on Drive and
isn't on disk yet (the next year's file) is downloaded too, and the pipeline
rolls over to it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .config import DATA_DIR, ORACLE_DIR, PROJECT_ROOT
from .io_oracle import _infer_year_from_name

logger = logging.getLogger("lps.refresh_oracle")

# The "Match Data" folder linked from https://oracleselixir.com/tools/downloads
OE_FOLDER_ID = "1gLSw0RLjBbtaNy0dgnGQDAZOHIgCe-HH"
SEASON_RE = re.compile(r"^(20\d{2})_LoL_esports_match_data_from_OraclesElixir\.csv$")
STATE_PATH = DATA_DIR / "cache" / "oracle_refresh.json"
# PROJECT_ROOT is lps/backend; python-sharp sits next to the lps checkout.
_PSHARP_DIR = Path(os.environ.get("PSHARP_PATH", PROJECT_ROOT.parent.parent / "python-sharp"))
TOKEN_PATH = _PSHARP_DIR / "token.json"
SCOPES = ["https://www.googleapis.com/auth/drive"]
_CHUNK = 32 * 1024 * 1024


class RefreshError(RuntimeError):
    """Drive couldn't be reached at all (no token, auth or listing failure)."""


@dataclass
class RefreshResult:
    """What one refresh run did, by season year."""

    updated: list[int] = field(default_factory=list)  # swapped in (incl. new seasons)
    added: list[int] = field(default_factory=list)  # subset of updated: not on disk before
    stale: list[int] = field(default_factory=list)  # --check only: differs from Drive
    failed: list[int] = field(default_factory=list)  # download rejected; old file kept


# --------------------------------------------------------------------------- #
# Drive
# --------------------------------------------------------------------------- #
def drive_service():
    """Drive v3 client on python-sharp's token. The token is refreshed in memory
    only: the refresh token doesn't change, and python-sharp owns writing the file."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    if not TOKEN_PATH.exists():
        raise RefreshError(
            f"no Google token at {TOKEN_PATH} (run any python-sharp Sheet() once to "
            "create it, or set PSHARP_PATH)"
        )
    try:
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
        if not creds.valid:
            creds.refresh(Request())
    except Exception as exc:  # expired/revoked refresh token, network down, ...
        raise RefreshError(f"Google auth failed: {exc}") from exc
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def list_folder(service) -> dict[str, dict]:
    """{file name: {id, name, md5Checksum, size, modifiedTime}} for OE's folder."""
    out: dict[str, dict] = {}
    token = None
    while True:
        resp = (
            service.files()
            .list(
                q=f"'{OE_FOLDER_ID}' in parents and trashed = false",
                fields="nextPageToken, files(id, name, md5Checksum, size, modifiedTime)",
                pageSize=100,
                pageToken=token,
            )
            .execute()
        )
        for f in resp.get("files", []):
            out[f["name"]] = f
        token = resp.get("nextPageToken")
        if not token:
            return out


def _download(service, file_id: str, dest: Path) -> None:
    from googleapiclient.http import MediaIoBaseDownload

    with open(dest, "wb") as fh:
        dl = MediaIoBaseDownload(
            fh, service.files().get_media(fileId=file_id), chunksize=_CHUNK
        )
        done = False
        while not done:
            _, done = dl.next_chunk(num_retries=3)


def _quota_error(exc: Exception) -> bool:
    status = getattr(getattr(exc, "resp", None), "status", None)
    return status == 403 and any(
        r in str(exc) for r in ("downloadQuotaExceeded", "Too many users", "quota")
    )


def fetch(service, remote: dict, dest: Path) -> None:
    """Download one Drive file to dest, through a private copy if the original's
    download quota is exhausted."""
    from googleapiclient.errors import HttpError

    try:
        _download(service, remote["id"], dest)
        return
    except HttpError as exc:
        if not _quota_error(exc):
            raise
        logger.info("  %s: download quota hit; going through a copy in your Drive", remote["name"])
    copy = (
        service.files()
        .copy(fileId=remote["id"], body={"name": f"lps-tmp-{remote['name']}"}, fields="id")
        .execute()
    )
    try:
        _download(service, copy["id"], dest)
    finally:
        service.files().delete(fileId=copy["id"]).execute()


# --------------------------------------------------------------------------- #
# local files
# --------------------------------------------------------------------------- #
def _md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _summary(path: Path) -> tuple[list[str], int]:
    """(header columns, game count) of a season CSV."""
    header = list(pd.read_csv(path, nrows=0).columns)
    games = pd.read_csv(path, usecols=["gameid"], low_memory=False)["gameid"].nunique()
    return header, games


def validate(old: Path | None, new: Path, force: bool) -> tuple[str | None, int, int]:
    """(why `new` must not replace `old`, or None if it's fine; old games; new games)."""
    try:
        new_header, new_games = _summary(new)
    except Exception as exc:
        return f"unreadable download ({exc!r})", 0, 0
    if old is None or not old.exists():
        return None, 0, new_games
    old_header, old_games = _summary(old)
    missing = [c for c in old_header if c not in new_header]
    if missing:
        more = "..." if len(missing) > 8 else ""
        return f"columns dropped: {', '.join(missing[:8])}{more}", old_games, new_games
    if new_games < old_games and not force:
        return f"game count dropped {old_games} -> {new_games} (--force to accept)", old_games, new_games
    return None, old_games, new_games


def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True))


def local_md5(path: Path, state: dict) -> str | None:
    """md5 of the local file, from the state cache while its size+mtime still match."""
    if not path.exists():
        return None
    st = path.stat()
    entry = state.get(path.name)
    if entry and entry.get("size") == st.st_size and entry.get("mtime_ns") == st.st_mtime_ns:
        return entry["md5"]
    md5 = _md5(path)
    state[path.name] = {"md5": md5, "size": st.st_size, "mtime_ns": st.st_mtime_ns}
    return md5


def _local_by_year() -> dict[int, Path]:
    """The season CSV on disk for each year (io_oracle's year-in-filename rule)."""
    out: dict[int, Path] = {}
    for p in sorted(ORACLE_DIR.glob("*.csv")):
        y = _infer_year_from_name(p)
        if y is not None:
            out.setdefault(y, p)
    return out


# --------------------------------------------------------------------------- #
# refresh
# --------------------------------------------------------------------------- #
def refresh(
    *, check: bool = False, force: bool = False, only: list[int] | None = None
) -> RefreshResult:
    """Bring data/oracle/ in line with OE's Drive folder. A file whose download
    fails or is rejected keeps its old copy (it's reported in `failed`); raises
    RefreshError only when Drive can't be reached at all."""
    service = drive_service()
    try:
        remote = list_folder(service)
    except Exception as exc:
        raise RefreshError(f"couldn't list OE's Drive folder: {exc}") from exc

    seasons = {
        int(m.group(1)): info for name, info in remote.items() if (m := SEASON_RE.match(name))
    }
    if not seasons:
        raise RefreshError("OE's Drive folder has no season CSVs (folder moved or renamed?)")

    local = _local_by_year()
    for y in sorted(set(local) - set(seasons)):
        logger.info("%s: not in OE's Drive folder (renamed?); keeping the local copy", local[y].name)

    ORACLE_DIR.mkdir(parents=True, exist_ok=True)
    state = load_state()
    result = RefreshResult()
    for year in sorted(seasons):
        if only and year not in only:
            continue
        info = seasons[year]
        old = local.get(year)
        if old is not None and local_md5(old, state) == info.get("md5Checksum"):
            continue
        size_mb = int(info.get("size", 0)) / 1e6
        what = "changed on Drive" if old is not None else "NEW season on Drive"
        if check:
            result.stale.append(year)
            logger.info("%s: %s (%s, %.0f MB)", info["name"], what, info["modifiedTime"], size_mb)
            continue
        logger.info(
            "%s: %s (%s); downloading %.0f MB", info["name"], what, info["modifiedTime"], size_mb
        )
        dest = ORACLE_DIR / info["name"]
        part = dest.with_name(f".{dest.name}.part")
        try:
            fetch(service, info, part)
            if _md5(part) != info.get("md5Checksum"):
                raise RuntimeError("md5 mismatch after download")
            reason, old_games, new_games = validate(old, part, force)
            if reason:
                raise RuntimeError(reason)
            os.replace(part, dest)
            if old is not None and old != dest:
                old.unlink()  # same season under a different local filename
                state.pop(old.name, None)
        except Exception as exc:
            result.failed.append(year)
            logger.warning("%s: NOT updated, keeping the old file: %s", info["name"], exc)
            part.unlink(missing_ok=True)
            continue
        st = dest.stat()
        state[dest.name] = {"md5": info["md5Checksum"], "size": st.st_size, "mtime_ns": st.st_mtime_ns}
        result.updated.append(year)
        if old is None:
            result.added.append(year)
        logger.info("%s: updated (%+d games, %d total)", dest.name, new_games - old_games, new_games)

    state["_last_run"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    if check:
        logger.info(
            "%d season file(s) differ from Drive: %s" % (len(result.stale), result.stale)
            if result.stale
            else "every season file matches Drive"
        )
    elif not result.updated:
        logger.info(
            "no season file changed"
            if not result.failed
            else f"no season file updated ({len(result.failed)} failed)"
        )
    return result


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="report what changed, download nothing")
    ap.add_argument("--force", action="store_true", help="accept a download whose game count dropped")
    ap.add_argument("--only", nargs="+", type=int, metavar="YEAR", help="only these seasons")
    args = ap.parse_args()
    try:
        result = refresh(check=args.check, force=args.force, only=args.only)
    except RefreshError as exc:
        logger.error("%s", exc)
        return 2
    return 1 if result.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
