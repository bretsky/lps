from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pandas as pd

from .config import ORACLE_DIR


YEAR_REGEX = re.compile(r"(20\d{2})")


def _infer_year_from_name(path: Path) -> Optional[int]:
	"""Try to extract the year from a filename like 'LeagueofLegends-2018.csv'."""
	m = YEAR_REGEX.search(path.name)
	if m:
		return int(m.group(1))
	return None


def list_oracle_files() -> list[Path]:
	"""Return all Oracle's Elixir CSV files in the oracle data directory."""
	return files


def load_oracle_year(year: int) -> pd.DataFrame:
	"""
	Load a single year of Oracle's Elixir data.

	This assumes one CSV per year with the year in the filename.
	If you have a different naming scheme, tweak the glob / filter.
	"""
	candidates = [p for p in list_oracle_files() if str(year) in p.name]
	if not candidates:
		raise FileNotFoundError(f"No Oracle CSV found for year {year}")
	if len(candidates) > 1:
		# If this happens, either refine naming or pick the correct one explicitly.
		raise RuntimeError(f"Multiple CSVs matched year {year}: {candidates}")

	path = candidates[0]
	df = pd.read_csv(path)
	df["year"] = year
	return df


def load_oracle_years(years: Iterable[int]) -> pd.DataFrame:
	"""Load multiple years and concatenate."""
	dfs = [load_oracle_year(y) for y in years]
	if not dfs:
		raise ValueError("No data loaded; check years / paths.")
	return pd.concat(dfs, ignore_index=True)


def load_oracle_all() -> pd.DataFrame:
	"""
	Load all Oracle CSVs in the directory and add a 'year' column
	inferred from filenames.
	"""
	files = list_oracle_files()
	if not files:
		raise FileNotFoundError(f"No CSV files found in {ORACLE_DIR}")

	dfs: list[pd.DataFrame] = []
	for path in files:
		year = _infer_year_from_name(path)
		df = pd.read_csv(path)
		if year is not None and "year" not in df.columns:
			df["year"] = year
		dfs.append(df)

	return pd.concat(dfs, ignore_index=True)
