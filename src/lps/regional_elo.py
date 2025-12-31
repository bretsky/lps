"""Compute regional Elo ratings from international tournament matches."""

from __future__ import annotations

import argparse
import csv
import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .config import LEAGUEPEDIA_DIR, LEAGUEPEDIA_INFO_DIR
from .team_regions import load_team_regions_by_year

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


# Elo configuration
DEFAULT_ELO = 1000  # Starting Elo for all regions
K_FACTOR = 32  # How much Elo changes per match (higher = more volatile)


class RegionalEloTracker:
    """Track Elo ratings for regions over time."""

    def __init__(self, default_elo: float = DEFAULT_ELO, k_factor: float = K_FACTOR):
        """
        Initialize the Elo tracker.

        Args:
            default_elo: Starting Elo rating for all regions.
            k_factor: K-factor for Elo calculations (how much ratings change per match).
        """
        self.default_elo = default_elo
        self.k_factor = k_factor
        self.elos: dict[str, float] = defaultdict(lambda: default_elo)
        self.match_history: list[dict[str, Any]] = []

    def get_elo(self, region: str) -> float:
        """Get current Elo for a region."""
        return self.elos[region]

    def expected_score(self, elo_a: float, elo_b: float) -> float:
        """
        Calculate expected score for team A against team B.

        Args:
            elo_a: Elo rating of region A.
            elo_b: Elo rating of region B.

        Returns:
            Expected score (win probability) for region A (0.0 to 1.0).
        """
        return 1.0 / (1.0 + 10 ** ((elo_b - elo_a) / 400))

    def update_elos(
        self,
        region_a: str,
        region_b: str,
        score_a: float,
        match_data: dict[str, Any] | None = None,
    ) -> tuple[float, float, float, float]:
        """
        Update Elo ratings based on match result.

        Args:
            region_a: Region of team A.
            region_b: Region of team B.
            score_a: Actual score for region A (1.0 = win, 0.0 = loss).
            match_data: Optional match metadata to store in history.

        Returns:
            Tuple of (old_elo_a, new_elo_a, old_elo_b, new_elo_b).
        """
        # Get current Elos
        old_elo_a = self.get_elo(region_a)
        old_elo_b = self.get_elo(region_b)

        # Calculate expected scores
        expected_a = self.expected_score(old_elo_a, old_elo_b)
        expected_b = 1.0 - expected_a

        # Calculate actual scores
        score_b = 1.0 - score_a

        # Update Elos
        new_elo_a = old_elo_a + self.k_factor * (score_a - expected_a)
        new_elo_b = old_elo_b + self.k_factor * (score_b - expected_b)

        self.elos[region_a] = new_elo_a
        self.elos[region_b] = new_elo_b

        # Record in history
        history_entry = {
            "region_a": region_a,
            "region_b": region_b,
            "old_elo_a": old_elo_a,
            "old_elo_b": old_elo_b,
            "new_elo_a": new_elo_a,
            "new_elo_b": new_elo_b,
            "expected_a": expected_a,
            "score_a": score_a,
            "elo_change_a": new_elo_a - old_elo_a,
            "elo_change_b": new_elo_b - old_elo_b,
        }
        if match_data:
            history_entry.update(match_data)
        self.match_history.append(history_entry)

        return old_elo_a, new_elo_a, old_elo_b, new_elo_b

    def get_all_elos(self) -> dict[str, float]:
        """Get current Elos for all regions."""
        return dict(self.elos)

    def reset_elos(self):
        """Reset all Elos to default."""
        self.elos.clear()
        self.match_history.clear()


def load_starting_elos(year: int, info_dir: Path | None = None) -> dict[str, float]:
    """
    Load starting Elos for regions from a CSV file.

    Args:
        year: The year to load starting Elos for.
        info_dir: Directory containing starting_elos_YEAR.csv files.

    Returns:
        Dictionary mapping region to starting Elo.
    """
    if info_dir is None:
        info_dir = LEAGUEPEDIA_INFO_DIR

    csv_file = info_dir / f"starting_elos_{year}.csv"

    if not csv_file.exists():
        logging.error(f"Starting Elos file not found: {csv_file}")
        logging.info(f"Please create {csv_file} with columns: region,starting_elo")
        raise FileNotFoundError(f"Missing starting Elos file: {csv_file}")

    starting_elos = {}

    with open(csv_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            region = row.get("region", "").strip()
            elo_str = row.get("starting_elo", "").strip()

            if not region or not elo_str:
                continue

            try:
                elo = float(elo_str)
                starting_elos[region] = elo
            except ValueError:
                logging.warning(f"Invalid Elo value for {region}: {elo_str}")
                continue

    logging.info(f"Loaded starting Elos for {len(starting_elos)} regions from {csv_file}")
    return starting_elos


def load_all_matches(matches_dir: Path) -> list[dict[str, Any]]:
    """
    Load all international matches from aggregated JSON files.

    Args:
        matches_dir: Directory containing *_all.json files.

    Returns:
        List of all matches.
    """
    all_matches = []

    if not matches_dir.exists():
        logging.error(f"Matches directory does not exist: {matches_dir}")
        return all_matches

    # Load all aggregated files
    json_files = list(matches_dir.glob("*_all.json"))
    logging.info(f"Found {len(json_files)} aggregated match files")

    for json_file in json_files:
        logging.info(f"Loading {json_file.name}...")
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                matches = json.load(f)
                all_matches.extend(matches)
        except Exception as e:
            logging.error(f"Error loading {json_file.name}: {e}")
            continue

    logging.info(f"Loaded {len(all_matches)} total matches")
    return all_matches


def get_team_names(match: dict[str, Any]) -> tuple[str | None, str | None]:
    """
    Extract team names from match, preferring TeamName over Team.

    Args:
        match: Match dictionary.

    Returns:
        Tuple of (team1_name, team2_name).
    """
    team1 = match.get("TeamName1") or match.get("Team1")
    team2 = match.get("TeamName2") or match.get("Team2")
    return team1, team2


def get_winner(match: dict[str, Any]) -> int | None:
    """
    Get the winner of a match.

    Args:
        match: Match dictionary.

    Returns:
        1 if team1 won, 2 if team2 won, None if unknown.
    """
    winner = match.get("Winner")
    if winner in [1, "1"]:
        return 1
    elif winner in [2, "2"]:
        return 2
    return None


def compute_regional_elos_for_year(
    year: int,
    matches: list[dict[str, Any]],
    team_regions: dict[str, str],
    starting_elos: dict[str, float],
    k_factor: float = K_FACTOR,
) -> tuple[dict[str, float], dict[str, float], list[dict[str, Any]]]:
    """
    Compute regional Elo ratings for a single year.

    Args:
        year: The year to process.
        matches: List of all international matches.
        team_regions: Team-to-region mappings for this year.
        starting_elos: Starting Elo for each region.
        k_factor: K-factor for Elo calculations.

    Returns:
        Tuple of (starting_elos, ending_elos, match_history).
    """
    # Initialize tracker with starting Elos
    tracker = RegionalEloTracker(default_elo=DEFAULT_ELO, k_factor=k_factor)
    for region, elo in starting_elos.items():
        tracker.elos[region] = elo

    # Parse and filter matches for this year
    year_matches = []
    for match in matches:
        datetime_str = match.get("DateTime UTC")
        if not datetime_str:
            continue

        # Parse datetime
        try:
            if isinstance(datetime_str, str):
                dt = datetime.fromisoformat(datetime_str.replace("Z", "+00:00"))
            else:
                dt = datetime_str
        except (ValueError, TypeError):
            continue

        # Only process matches from the specified year
        if dt.year != year:
            continue

        year_matches.append((dt, match))

    # Sort chronologically
    year_matches.sort(key=lambda x: x[0])
    logging.info(f"Processing {len(year_matches)} matches for year {year}")

    # Process matches
    for dt, match in year_matches:
        # Extract teams and winner
        team1, team2 = get_team_names(match)
        winner = get_winner(match)

        if not team1 or not team2 or winner is None:
            continue

        # Get regions
        region1 = team_regions.get(team1)
        region2 = team_regions.get(team2)

        if not region1 or not region2:
            continue

        # Skip teams with region "N/A"
        if region1.upper() == "N/A" or region2.upper() == "N/A":
            continue

        # Skip intra-regional matches
        if region1 == region2:
            continue

        # Determine score (1.0 = team1 won, 0.0 = team2 won)
        score1 = 1.0 if winner == 1 else 0.0

        # Update Elos
        tracker.update_elos(
            region1,
            region2,
            score1,
            match_data={
                "year": year,
                "date": dt.isoformat(),
                "team1": team1,
                "team2": team2,
                "winner": winner,
                "tournament": match.get("Name", ""),
            },
        )

    # Get final Elos
    ending_elos = tracker.get_all_elos()

    # Ensure all regions from starting_elos are in ending_elos
    for region in starting_elos:
        if region not in ending_elos:
            ending_elos[region] = starting_elos[region]

    return starting_elos, ending_elos, tracker.match_history


def compute_regional_elos_by_year(
    matches: list[dict[str, Any]],
    regions_by_year: dict[int, dict[str, str]],
    default_elo: float = DEFAULT_ELO,
    k_factor: float = K_FACTOR,
    reset_yearly: bool = False,
) -> dict[int, dict[str, tuple[float, float]]]:
    """
    Compute regional Elo ratings year by year.

    Args:
        matches: List of all international matches.
        regions_by_year: Team-to-region mappings by year.
        default_elo: Starting Elo rating.
        k_factor: K-factor for Elo calculations.
        reset_yearly: If True, reset Elos to default at start of each year.
                      If False, carry over Elos from previous year.

    Returns:
        Dictionary mapping year to {region: (starting_elo, ending_elo)}.
    """
    tracker = RegionalEloTracker(default_elo, k_factor)
    elos_by_year = {}

    # Parse and sort matches by datetime
    matches_with_datetime = []
    for match in matches:
        datetime_str = match.get("DateTime UTC")
        if not datetime_str:
            continue

        # Parse datetime
        try:
            if isinstance(datetime_str, str):
                dt = datetime.fromisoformat(datetime_str.replace("Z", "+00:00"))
            else:
                dt = datetime_str
        except (ValueError, TypeError) as e:
            logging.warning(f"Could not parse datetime: {datetime_str} ({e})")
            continue

        matches_with_datetime.append((dt, match))

    # Sort chronologically
    matches_with_datetime.sort(key=lambda x: x[0])
    logging.info(f"Processing {len(matches_with_datetime)} matches chronologically")

    # Process matches year by year
    current_year = None
    year_starting_elos = {}

    for dt, match in matches_with_datetime:
        year = dt.year

        # Check if we've moved to a new year
        if current_year != year:
            # Record ending Elos for previous year
            if current_year is not None:
                year_ending_elos = tracker.get_all_elos()
                elos_by_year[current_year] = {
                    region: (
                        year_starting_elos.get(region, default_elo),  # Use default if region is new
                        year_ending_elos[region]
                    )
                    for region in year_ending_elos
                }
                logging.info(
                    f"Year {current_year} complete: {len(year_ending_elos)} regions tracked"
                )

            # Start new year
            current_year = year
            logging.info(f"\nProcessing year {year}...")

            # Record starting Elos for new year
            year_starting_elos = tracker.get_all_elos().copy()

            # Reset Elos if configured
            if reset_yearly and year != min(regions_by_year.keys()):
                logging.info(f"  Resetting Elos to {default_elo} for year {year}")
                tracker.reset_elos()
                year_starting_elos = tracker.get_all_elos().copy()

        # Get team regions for this year
        year_regions = regions_by_year.get(year, {})
        if not year_regions:
            logging.warning(f"No region mappings for year {year}, skipping matches")
            continue

        # Extract teams and winner
        team1, team2 = get_team_names(match)
        winner = get_winner(match)

        if not team1 or not team2 or winner is None:
            continue

        # Get regions
        region1 = year_regions.get(team1)
        region2 = year_regions.get(team2)

        if not region1 or not region2:
            # Skip matches where we don't have region data
            continue

        # Skip teams with region "N/A" (no assigned region)
        if region1.upper() == "N/A" or region2.upper() == "N/A":
            continue

        # Skip intra-regional matches (same region vs same region)
        if region1 == region2:
            continue

        # Determine score (1.0 = team1 won, 0.0 = team2 won)
        score1 = 1.0 if winner == 1 else 0.0

        # Update Elos
        tracker.update_elos(
            region1,
            region2,
            score1,
            match_data={
                "year": year,
                "date": dt.isoformat(),
                "team1": team1,
                "team2": team2,
                "winner": winner,
                "tournament": match.get("Name", ""),
            },
        )

    # Record ending Elos for final year
    if current_year is not None:
        year_ending_elos = tracker.get_all_elos()
        elos_by_year[current_year] = {
            region: (
                year_starting_elos.get(region, default_elo),  # Use default if region is new
                year_ending_elos[region]
            )
            for region in year_ending_elos
        }
        logging.info(
            f"Year {current_year} complete: {len(year_ending_elos)} regions tracked"
        )

    return elos_by_year


def save_elos_to_csv(
    elos_by_year: dict[int, dict[str, tuple[float, float]]],
    output_file: Path,
):
    """
    Save regional Elos to CSV file.

    Args:
        elos_by_year: Dictionary mapping year to {region: (starting_elo, ending_elo)}.
        output_file: Path to save CSV.
    """
    output_file.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for year in sorted(elos_by_year.keys()):
        year_elos = elos_by_year[year]
        for region in sorted(year_elos.keys()):
            starting_elo, ending_elo = year_elos[region]
            rows.append({
                "year": year,
                "region": region,
                "starting_elo": round(starting_elo, 2),
                "ending_elo": round(ending_elo, 2),
                "elo_change": round(ending_elo - starting_elo, 2),
            })

    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["year", "region", "starting_elo", "ending_elo", "elo_change"]
        )
        writer.writeheader()
        writer.writerows(rows)

    logging.info(f"Saved regional Elos to {output_file}")


def print_elo_summary(elos_by_year: dict[int, dict[str, tuple[float, float]]]):
    """Print summary of regional Elos by year."""
    logging.info("\n" + "=" * 80)
    logging.info("REGIONAL ELO SUMMARY")
    logging.info("=" * 80)

    for year in sorted(elos_by_year.keys()):
        logging.info(f"\nYear {year}:")
        logging.info(f"  {'Region':<8} {'Start Elo':<12} {'End Elo':<12} {'Change':<10}")
        logging.info("  " + "-" * 50)

        year_elos = elos_by_year[year]
        # Sort by ending Elo (descending)
        sorted_regions = sorted(
            year_elos.items(), key=lambda x: x[1][1], reverse=True
        )

        for region, (start_elo, end_elo) in sorted_regions:
            change = end_elo - start_elo
            sign = "+" if change >= 0 else ""
            logging.info(
                f"  {region:<8} {start_elo:>8.1f}      {end_elo:>8.1f}      "
                f"{sign}{change:>6.1f}"
            )


def main():
    """Main entry point for computing regional Elos."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Compute regional Elo ratings from international tournament matches"
    )
    parser.add_argument(
        "--year",
        type=int,
        help="Year to compute Elos for (requires starting_elos_YEAR.csv)",
    )
    args = parser.parse_args()

    logging.info("Computing regional Elo ratings from international matches...")

    # Load matches
    matches_dir = LEAGUEPEDIA_DIR / "matches"
    matches = load_all_matches(matches_dir)

    if not matches:
        logging.error("No matches found. Have you downloaded matches?")
        logging.info("Run: python -m lps.fetch_international_matches")
        return

    # Load team regions
    regions_by_year = load_team_regions_by_year()

    if not regions_by_year:
        logging.error("No team region mappings found. Have you filled in the CSVs?")
        logging.info("Run: python -m lps.extract_team_names")
        logging.info("Then fill in the region column for each team_regions_YYYY.csv")
        return

    # Single year mode (with custom starting Elos)
    if args.year:
        year = args.year
        logging.info(f"\nComputing Elos for year {year}...")

        # Load starting Elos
        try:
            starting_elos = load_starting_elos(year)
        except FileNotFoundError:
            logging.error(f"Cannot compute Elos for {year} without starting_elos_{year}.csv")
            logging.info(f"Please create data/leaguepedia/info/starting_elos_{year}.csv with columns:")
            logging.info("  region,starting_elo")
            logging.info("Example:")
            logging.info("  NA,1000")
            logging.info("  EU,1050")
            logging.info("  KR,1200")
            return

        # Get team regions for this year
        team_regions = regions_by_year.get(year, {})
        if not team_regions:
            logging.error(f"No team region mappings found for year {year}")
            logging.info(f"Please fill in data/leaguepedia/team_regions_{year}.csv")
            return

        # Compute Elos for this year
        starting, ending, match_history = compute_regional_elos_for_year(
            year, matches, team_regions, starting_elos, K_FACTOR
        )

        # Print results
        logging.info(f"\n{'='*80}")
        logging.info(f"Year {year} Results:")
        logging.info(f"{'='*80}")
        logging.info(f"  {'Region':<8} {'Start Elo':<12} {'End Elo':<12} {'Change':<10} {'Matches':<10}")
        logging.info("  " + "-" * 70)

        # Count matches per region
        region_match_counts = {}
        for match in match_history:
            region_a = match["region_a"]
            region_b = match["region_b"]
            region_match_counts[region_a] = region_match_counts.get(region_a, 0) + 1
            region_match_counts[region_b] = region_match_counts.get(region_b, 0) + 1

        # Sort by ending Elo (descending)
        sorted_regions = sorted(ending.items(), key=lambda x: x[1], reverse=True)

        for region, end_elo in sorted_regions:
            start_elo = starting.get(region, DEFAULT_ELO)
            change = end_elo - start_elo
            matches_count = region_match_counts.get(region, 0)
            sign = "+" if change >= 0 else ""
            logging.info(
                f"  {region:<8} {start_elo:>8.1f}      {end_elo:>8.1f}      "
                f"{sign}{change:>6.1f}      {matches_count:>4}"
            )

        # Save ending Elos for next year
        output_file = LEAGUEPEDIA_INFO_DIR / f"ending_elos_{year}.csv"
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["region", "ending_elo"])
            for region in sorted(ending.keys()):
                writer.writerow([region, round(ending[region], 2)])

        logging.info(f"\nEnding Elos saved to {output_file}")
        logging.info(f"Use this as starting_elos_{year + 1}.csv for next year")

    # Multi-year mode (legacy)
    else:
        logging.info("\nComputing Elos with carry-over between years...")
        elos_by_year = compute_regional_elos_by_year(
            matches,
            regions_by_year,
            default_elo=DEFAULT_ELO,
            k_factor=K_FACTOR,
            reset_yearly=False,  # Carry over Elos from year to year
        )

        # Save results
        output_file = LEAGUEPEDIA_DIR / "regional_elos.csv"
        save_elos_to_csv(elos_by_year, output_file)

        # Print summary
        print_elo_summary(elos_by_year)

        logging.info(f"\nDone! Regional Elos saved to {output_file}")


if __name__ == "__main__":
    main()
