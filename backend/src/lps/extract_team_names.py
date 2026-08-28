"""Extract unique team names from Leaguepedia matches and create a CSV for region mapping."""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path

from .config import INFO_DIR

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def get_team_name_from_match(match: dict, team_number: int) -> str | None:
    """
    Extract the canonical team name from a match, preferring TeamName over Team.

    Args:
        match: Match dictionary from Leaguepedia.
        team_number: 1 or 2 for Team1/Team2.

    Returns:
        The canonical team name, or None if not found.
    """
    # Try TeamName first (canonical name via redirects)
    team_name_field = f"TeamName{team_number}"
    if team_name_field in match and match[team_name_field]:
        return match[team_name_field].strip()

    # Fall back to Team (display name)
    team_field = f"Team{team_number}"
    if team_field in match and match[team_field]:
        return match[team_field].strip()

    return None


def extract_team_names_by_year(matches_dir: Path) -> dict[int, set[str]]:
    """
    Extract unique team names from all match JSON files, grouped by year.

    Args:
        matches_dir: Directory containing match JSON files.

    Returns:
        Dictionary mapping year to set of unique team names.
    """
    teams_by_year = {}

    if not matches_dir.exists():
        logging.error(f"Matches directory does not exist: {matches_dir}")
        return teams_by_year

    # Find all JSON files
    json_files = list(matches_dir.glob("*_all.json"))
    logging.info(f"Found {len(json_files)} JSON files in {matches_dir}")

    # Process each JSON file
    for json_file in json_files:
        logging.info(f"Processing {json_file.name}...")

        try:
            with open(json_file, "r", encoding="utf-8") as f:
                matches = json.load(f)

            # Extract team names from each match, grouped by year
            for match in matches:
                # Get year from match data
                year = match.get("Year")
                if not year:
                    # Try to extract from tournament name or datetime
                    name = match.get("Name", "")
                    # Look for year pattern in name (e.g., "Mid-Season Invitational/2024")
                    import re
                    year_match = re.search(r'/(\d{4})', name)
                    if year_match:
                        year = int(year_match.group(1))
                    else:
                        # Try to get from datetime
                        datetime_str = match.get("DateTime UTC", "")
                        if datetime_str:
                            year_match = re.search(r'^(\d{4})', datetime_str)
                            if year_match:
                                year = int(year_match.group(1))

                if not year:
                    logging.warning(f"Could not determine year for match: {match.get('MatchId', 'unknown')}")
                    continue

                # Convert to int if it's a string
                year = int(year)

                # Initialize set for this year if needed
                if year not in teams_by_year:
                    teams_by_year[year] = set()

                # Get both teams
                team1 = get_team_name_from_match(match, 1)
                team2 = get_team_name_from_match(match, 2)

                if team1:
                    teams_by_year[year].add(team1)
                if team2:
                    teams_by_year[year].add(team2)

        except Exception as e:
            logging.error(f"Error processing {json_file.name}: {e}")
            continue

    # Log summary
    total_teams = sum(len(teams) for teams in teams_by_year.values())
    logging.info(f"Found {total_teams} team entries across {len(teams_by_year)} years")
    for year in sorted(teams_by_year.keys()):
        logging.info(f"  {year}: {len(teams_by_year[year])} teams")

    return teams_by_year


def save_teams_to_csv(team_names: set[str], output_file: Path) -> None:
    """
    Save team names to a CSV file with an empty region column.

    Args:
        team_names: Set of unique team names.
        output_file: Path to save the CSV file.
    """
    # Sort team names alphabetically for easier manual filling
    sorted_teams = sorted(team_names)

    # Create parent directory if it doesn't exist
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # Write to CSV
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        # Write header
        writer.writerow(["team_name", "region"])

        # Write team names with empty region
        for team_name in sorted_teams:
            writer.writerow([team_name, ""])

    logging.info(f"Saved {len(sorted_teams)} teams to {output_file}")


def main():
    """Main entry point for extracting team names."""
    from .config import LEAGUEPEDIA_DIR

    matches_dir = LEAGUEPEDIA_DIR / "matches"

    logging.info("Extracting team names from Leaguepedia matches...")

    # Extract team names grouped by year
    teams_by_year = extract_team_names_by_year(matches_dir)

    if not teams_by_year:
        logging.warning("No team names found. Have you downloaded matches yet?")
        logging.info("Run: python -m lps.fetch_international_matches")
        return

    # Save one CSV per year to info directory
    for year in sorted(teams_by_year.keys()):
        output_file = INFO_DIR / f"team_regions_{year}.csv"
        team_names = teams_by_year[year]
        save_teams_to_csv(team_names, output_file)

    logging.info(f"\nDone! Created {len(teams_by_year)} CSV files (one per year)")
    logging.info(f"Location: {INFO_DIR}/team_regions_YYYY.csv")
    logging.info("\nPlease fill in the regions for each year:")
    logging.info("  - team_name: The team name (already filled)")
    logging.info("  - region: Your region code (e.g., NA, EU, KR, CN, LMS/PCS, BR, etc.)")
    logging.info("\nNote: Regions can change between years (e.g., LMS → PCS in 2020)")


if __name__ == "__main__":
    main()
