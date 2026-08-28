"""Utilities for loading and managing team region mappings."""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from .config import INFO_DIR

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def load_team_regions_by_year(info_dir: Path | None = None) -> dict[int, dict[str, str]]:
    """
    Load team-to-region mappings from all year-specific CSV files.

    Args:
        info_dir: Directory containing team_regions_YYYY.csv files.
                  Defaults to INFO_DIR.

    Returns:
        Dictionary mapping year to (team_name -> region) dictionary.
    """
    if info_dir is None:
        info_dir = INFO_DIR

    regions_by_year = {}

    # Find all team_regions_YYYY.csv files
    csv_files = list(info_dir.glob("team_regions_*.csv"))

    if not csv_files:
        logging.error(f"No team_regions_YYYY.csv files found in {info_dir}")
        logging.info("Run: python -m lps.extract_team_names")
        return {}

    for csv_file in sorted(csv_files):
        # Extract year from filename
        try:
            year = int(csv_file.stem.split("_")[-1])
        except ValueError:
            logging.warning(f"Could not extract year from filename: {csv_file.name}")
            continue

        team_regions = {}

        with open(csv_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for row in reader:
                team_name = row.get("team_name", "").strip()
                region = row.get("region", "").strip()

                if team_name and region:
                    team_regions[team_name] = region

        regions_by_year[year] = team_regions
        logging.info(f"Loaded {len(team_regions)} team-region mappings for {year}")

    total_mappings = sum(len(regions) for regions in regions_by_year.values())
    logging.info(f"Total: {total_mappings} mappings across {len(regions_by_year)} years")

    return regions_by_year


def load_team_regions(year: int, info_dir: Path | None = None) -> dict[str, str]:
    """
    Load team-to-region mappings for a specific year.

    Args:
        year: The year to load mappings for.
        info_dir: Directory containing team_regions_YYYY.csv files.
                  Defaults to INFO_DIR.

    Returns:
        Dictionary mapping team name to region for the specified year.
    """
    if info_dir is None:
        info_dir = INFO_DIR

    csv_file = info_dir / f"team_regions_{year}.csv"

    if not csv_file.exists():
        logging.error(f"Team regions CSV not found for year {year}: {csv_file}")
        logging.info("Run: python -m lps.extract_team_names")
        return {}

    team_regions = {}

    with open(csv_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:
            team_name = row.get("team_name", "").strip()
            region = row.get("region", "").strip()

            if team_name:
                if region:
                    team_regions[team_name] = region
                else:
                    # Warn about teams without regions
                    logging.warning(f"Team '{team_name}' in {year} has no region assigned")

    logging.info(f"Loaded {len(team_regions)} team-region mappings for {year}")
    return team_regions


def get_team_region(
    team_name: str,
    year: int,
    regions_by_year: dict[int, dict[str, str]] | None = None
) -> str | None:
    """
    Get the region for a team in a specific year.

    Args:
        team_name: The team name to look up.
        year: The year to look up.
        regions_by_year: Dictionary of year-specific team-region mappings.
                         If None, will load from CSVs.

    Returns:
        The region code (e.g., 'NA', 'EU', 'KR'), or None if not found.
    """
    if regions_by_year is None:
        regions_by_year = load_team_regions_by_year()

    year_regions = regions_by_year.get(year, {})
    return year_regions.get(team_name)


def validate_team_regions(info_dir: Path | None = None) -> dict[int, tuple[int, int]]:
    """
    Validate all year-specific team regions CSVs and report statistics.

    Args:
        info_dir: Directory containing team_regions_YYYY.csv files.
                  Defaults to INFO_DIR.

    Returns:
        Dictionary mapping year to (teams_with_regions, teams_without_regions).
    """
    if info_dir is None:
        info_dir = INFO_DIR

    # Find all team_regions_YYYY.csv files
    csv_files = list(info_dir.glob("team_regions_*.csv"))

    if not csv_files:
        logging.error(f"No team_regions_YYYY.csv files found in {info_dir}")
        return {}

    stats_by_year = {}

    logging.info(f"\n{'='*60}")
    logging.info("Team Regions Validation (by year)")
    logging.info(f"{'='*60}")

    for csv_file in sorted(csv_files):
        # Extract year from filename
        try:
            year = int(csv_file.stem.split("_")[-1])
        except ValueError:
            logging.warning(f"Could not extract year from filename: {csv_file.name}")
            continue

        teams_with_regions = 0
        teams_without_regions = 0

        with open(csv_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for row in reader:
                team_name = row.get("team_name", "").strip()
                region = row.get("region", "").strip()

                if not team_name:
                    continue

                if region:
                    teams_with_regions += 1
                else:
                    teams_without_regions += 1

        total = teams_with_regions + teams_without_regions
        stats_by_year[year] = (teams_with_regions, teams_without_regions)

        if total > 0:
            pct = teams_with_regions / total * 100
            status = "✓" if teams_without_regions == 0 else "⚠"
            logging.info(
                f"{status} {year}: {teams_with_regions}/{total} teams ({pct:.1f}%) "
                f"[{teams_without_regions} missing]"
            )

    # Summary
    total_with = sum(stats[0] for stats in stats_by_year.values())
    total_without = sum(stats[1] for stats in stats_by_year.values())
    grand_total = total_with + total_without

    logging.info(f"\n{'='*60}")
    logging.info("Overall Summary:")
    if grand_total > 0:
        logging.info(f"  Total teams (all years): {grand_total}")
        logging.info(f"  Teams with regions: {total_with} ({total_with/grand_total*100:.1f}%)")
        logging.info(f"  Teams without regions: {total_without} ({total_without/grand_total*100:.1f}%)")
    logging.info(f"{'='*60}")

    return stats_by_year


if __name__ == "__main__":
    # When run directly, validate the team regions CSV
    validate_team_regions()
