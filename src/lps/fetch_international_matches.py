"""Fetch international tournament matches from Leaguepedia for regional Elo estimation."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from tqdm import tqdm

from .config import LEAGUEPEDIA_DIR
from .lp_client import LPClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


# Tournament patterns to fetch
# These are league names or name patterns that will be matched
INTERNATIONAL_TOURNAMENTS = {
    "MSI": {"tournament": "MSI", "league": ["Mid-Season Invitational"]},  # MSI
    "Worlds": {"tournament": "Worlds", "league": ["World Championship"]},  # Worlds
    "IEM": {"tournament": "IEM", "league": ["Intel Extreme Masters", "IEM Challenger"]},  # Intel Extreme Masters
    "FirstStand": {"tournament": "First Stand", "league": ["First Stand"]},  # First Stand
    "IWCT": {"tournament": "IWCT", "league": ["2014 International Wildcard Tournament", "International Wildcard Tournament Chile", "International Wildcard Tournament Turkey"]},  # International Wildcard Tournament
    "IWCQ": {"tournament": "IWCQ", "league": ["2016 International Wildcard Qualifier"]},  # International Wildcard Qualifier
    "IWCI": {"tournament": "IWCI", "league": ["International Wildcard Invitational"]},  # International Wildcard Invitational
    "EWC": {"tournament": "Esports World Cup", "league": ["Esports World Cup"]},  # Esports World Cup
    "RiftRivals": {"tournament": "Rift Rivals", "league": ["Rift Rivals 2017 GPL-LJL-OPL", "Rift Rivals 2017 LCK-LPL-LMS", "Rift Rivals 2017 LCL-TCL", "Rift Rivals 2017 LLN-CLS-CBLOL", "Rift Rivals 2017 NA-EU", "Rift Rivals 2018 LLN-CLS-CBLOL", "Rift Rivals 2018 SEA-LJL-OPL"]},  # Rift Rivals
    "MidSeasonCup": {"tournament": "Mid-Season Cup", "league": ["Mid-Season Cup 2020"]},  # Mid-Season Cup
    "MidSeasonShowdown": {"tournament": "Mid-Season Showdown", "league": ["Riot Games"]},  # Mid-Season Showdown
}

# Year range to fetch
START_YEAR = 2010  # LoL esports started around 2010-2011
END_YEAR = 2025  # Current year + 1 for safety


def sanitize_filename(name: str) -> str:
    """
    Sanitize a string to be used as a filename.

    Args:
        name: The name to sanitize.

    Returns:
        Sanitized filename-safe string.
    """
    # Replace problematic characters
    safe_name = name.replace("/", "_").replace("\\", "_").replace(":", "_")
    safe_name = safe_name.replace(" ", "_").replace("'", "").replace('"', "")
    return safe_name


def save_matches_to_json(matches: list[dict[str, Any]], filepath: Path) -> None:
    """
    Save matches to a JSON file.

    Args:
        matches: List of match dictionaries.
        filepath: Path to save the JSON file.
    """
    # Create parent directory if it doesn't exist
    filepath.parent.mkdir(parents=True, exist_ok=True)

    # Convert datetime objects to strings for JSON serialization
    serializable_matches = []
    for match in matches:
        match_copy = match.copy()
        datetime_val = match_copy.get("DateTime UTC")
        if datetime_val:
            # Only call isoformat() if it's a datetime object
            if hasattr(datetime_val, "isoformat"):
                match_copy["DateTime UTC"] = datetime_val.isoformat()
            # Otherwise it's already a string, leave it as is
        serializable_matches.append(match_copy)

    # Save to JSON
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(serializable_matches, f, indent=2, ensure_ascii=False)

    logging.info(f"Saved {len(matches)} matches to {filepath}")


def load_matches_from_json(filepath: Path) -> list[dict[str, Any]]:
    """
    Load matches from a JSON file.

    Args:
        filepath: Path to the JSON file.

    Returns:
        List of match dictionaries.
    """
    if not filepath.exists():
        return []

    with open(filepath, "r", encoding="utf-8") as f:
        matches = json.load(f)

    logging.info(f"Loaded {len(matches)} matches from {filepath}")
    return matches


def fetch_all_international_matches(
    client: LPClient,
    output_dir: Path | None = None,
    force_refetch: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    """
    Fetch all international tournament matches and save them to JSON files.

    Args:
        client: Leaguepedia client instance.
        output_dir: Directory to save JSON files (defaults to LEAGUEPEDIA_DIR / "matches").
        force_refetch: If True, refetch even if files already exist.

    Returns:
        Dictionary mapping tournament category to list of matches.
    """
    if output_dir is None:
        output_dir = LEAGUEPEDIA_DIR / "matches"

    output_dir.mkdir(parents=True, exist_ok=True)

    all_matches = {}

    # First, get all tournaments in our year range
    logging.info(f"Fetching tournaments from {START_YEAR} to {END_YEAR}...")
    tournaments = client.get_tournaments((START_YEAR, END_YEAR))
    logging.info(f"Found {len(tournaments)} tournaments total")

    # Group tournaments by category
    tournament_groups = {category: [] for category in INTERNATIONAL_TOURNAMENTS}
    all_tournaments = []
    for tournament in tournaments:
        league = tournament.get("League", "")
        name = tournament.get("Name", "")
        year = tournament.get("Year", "")
        all_tournaments.append({"league": league, "name": name, "year": year})

        # Skip Regional Finals tournaments (not international)
        if league == "World Championship" and "Regional Finals" in name:
            print(f"Skipping Regional Finals tournament: {name}")
            continue

        # Check if this tournament matches any of our patterns
        for category, pattern in INTERNATIONAL_TOURNAMENTS.items():
            pattern_leagues = pattern["league"]
            if league in pattern_leagues:
                print(f"Found {league} in {pattern_leagues}")
                if pattern["tournament"] in name:
                    tournament_groups[category].append(tournament)
                    break
    with open(output_dir / "all_tournaments.json", "w", encoding="utf-8") as f:
        json.dump(all_tournaments, f, indent=2, ensure_ascii=False)

    # Fetch matches for each category
    for category, tournaments_in_category in tournament_groups.items():
        logging.info(f"{'='*60}")
        logging.info(f"Fetching {category} matches...")
        logging.info(f"{'='*60}")
        logging.info(f"Found {len(tournaments_in_category)} {category} tournaments")

        category_matches = []

        for tournament in tqdm(tournaments_in_category, desc=f"Fetching {category}"):
            tournament_name = tournament.get("Name", "Unknown")
            year = tournament.get("Year", "Unknown")

            # Create filename for this tournament
            safe_name = sanitize_filename(tournament_name)
            filepath = output_dir / f"{category}_{safe_name}.json"

            # Check if we already have this data
            if filepath.exists() and not force_refetch:
                logging.info(f"Loading cached data for {tournament_name}...")
                matches = load_matches_from_json(filepath)
            else:
                # Fetch matches for this tournament
                logging.info(f"Fetching matches for {tournament_name} ({year})...")
                matches = client.get_matches_by_tournament(tournament_name)

                # Save to JSON
                if matches:
                    save_matches_to_json(matches, filepath)
                else:
                    logging.warning(f"No matches found for {tournament_name}")

            category_matches.extend(matches)

        all_matches[category] = category_matches
        logging.info(f"Total {category} matches: {len(category_matches)}")

        # Save aggregated file for this category
        aggregated_filepath = output_dir / f"{category}_all.json"
        save_matches_to_json(category_matches, aggregated_filepath)

    # Summary
    logging.info(f"{'='*60}")
    logging.info("SUMMARY")
    logging.info(f"{'='*60}")
    total_matches = 0
    for category, matches in all_matches.items():
        logging.info(f"{category}: {len(matches)} matches")
        total_matches += len(matches)
    logging.info(f"TOTAL: {total_matches} matches")

    return all_matches


def main():
    """Main entry point for fetching international matches."""
    logging.info("Initializing Leaguepedia client...")
    client = LPClient()

    if client.client is None:
        logging.error("Failed to initialize Leaguepedia client. Check credentials.")
        return

    logging.info("Fetching international tournament matches...")
    all_matches = fetch_all_international_matches(
        client,
        force_refetch=False,  # Set to True to refetch everything
    )

    logging.info("Done!")


if __name__ == "__main__":
    main()
