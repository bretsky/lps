"""Leaguepedia client for querying match data."""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Optional

import pytz
from mwclient.errors import APIError, MaximumRetriesExceeded
from mwrogue.auth_credentials import AuthCredentials
from mwrogue.esports_client import EsportsClient

from .config import LP_PASSWORD, LP_USERNAME


class LPClient:
    """Client for querying Leaguepedia data via Cargo."""

    def __init__(self, max_backoff: int = 256):
        """
        Initialize the Leaguepedia client.

        Args:
            max_backoff: Maximum backoff time in seconds for retries.
        """
        try:
            credentials = AuthCredentials(username=LP_USERNAME, password=LP_PASSWORD)
            self.client = EsportsClient("lol", credentials=credentials)
        except Exception as e:
            print(f"Error initializing EsportsClient: {e}")
            self.client = None
        self.backoff = 32
        self.init_backoff = 32
        self.max_backoff = max_backoff

    def query(self, **kwargs) -> list[dict]:
        """
        Issues a cargo query to Leaguepedia.

        Common params:
            tables: Comma-separated table names
            join_on: Join conditions
            fields: Comma-separated field names
            order_by: Order by clause
            where: Where clause
            group_by: Group by clause

        Returns:
            List of rows from the query.
        """
        result = []
        if self.client is None:
            return result

        # Paginate through results (Cargo returns max 500 rows per query)
        while len(result) % 500 == 0:
            try:
                batch = self.client.cargo_client.query(
                    limit=500, offset=len(result), **kwargs
                )
                result.extend(batch)
                self.backoff = self.init_backoff

                # If the batch is empty, we've reached the end
                if not batch:
                    break

            except (APIError, MaximumRetriesExceeded) as e:
                print(f"API error: {e}")
                print(f"Sleeping for {self.backoff} seconds...")
                time.sleep(self.backoff)
                self.backoff *= 2

                if self.backoff > self.max_backoff:
                    print(f"Max backoff reached ({self.max_backoff}s), giving up")
                    break

        return result

    def get_league_shortcodes(self, years: tuple[int, int]) -> dict[str, str]:
        """
        Get mapping of league short codes to full league names.

        Args:
            years: Tuple of (start_year, end_year) inclusive.

        Returns:
            Dict mapping league short code to full league name.
        """
        leagues_dicts_list = self.query(
            tables="Tournaments, Leagues",
            fields="Leagues.League, Leagues.League_Short",
            group_by="Leagues.League",
            where=f"Tournaments.Year >= {years[0]} AND Tournaments.Year <= {years[1]}",
            join_on="Tournaments.League = Leagues.League",
        )
        return {league["League Short"]: league["League"] for league in leagues_dicts_list}

    def get_tournaments(self, years: tuple[int, int]) -> list[dict]:
        """
        Get all tournaments within a year range.

        Args:
            years: Tuple of (start_year, end_year) inclusive.

        Returns:
            List of tournament dicts with League and Name fields.
        """
        tournaments = self.query(
            tables="Tournaments",
            fields="Tournaments.League, Tournaments.Name, Tournaments.Year",
            where=f"Tournaments.Year >= {years[0]} AND Tournaments.Year <= {years[1]}",
        )
        return tournaments

    def get_matches(
        self,
        start: datetime,
        end: datetime,
        league: Optional[str] = None,
    ) -> list[dict]:
        """
        Get matches within a date range, optionally filtered by league.

        Args:
            start: Start datetime (will be extended by 24h for safety).
            end: End datetime (will be extended by 24h for safety).
            league: Optional league name or tournament name to filter by.

        Returns:
            List of match dicts with tournament info, teams, winner, etc.
        """
        # Add buffer to handle timezone issues
        start_buffered = start - timedelta(hours=24)
        end_buffered = end + timedelta(hours=24)

        print(f"Querying matches: {start_buffered} to {end_buffered}, league={league}")

        where = f"MS.DateTime_UTC >= '{start_buffered}' AND MS.DateTime_UTC <= '{end_buffered}'"
        if league is not None:
            # Escape single quotes
            league_escaped = league.replace("'", "\\'")
            where += f" AND (T.League = '{league_escaped}' OR T.Name = '{league_escaped}' AND T.League IS NULL)"

        results = self.query(
            tables="Tournaments=T, MatchSchedule=MS, TeamRedirects=TR1, TeamRedirects=TR2",
            fields=(
                "T.Name, T.League, MS.DateTime_UTC, MS.Team1, MS.Team2, MS.Winner, MS.Team1Final, MS.Team2Final, "
                "MS.OverviewPage, MS.MatchId, MS.MatchDay, TR1._pageName=TeamName1, TR2._pageName=TeamName2"
            ),
            where=where,
            join_on="T.OverviewPage=MS.OverviewPage, MS.Team1=TR1.AllName, MS.Team2=TR2.AllName",
        )

        # Parse datetime strings
        for result in results:
            try:
                result["DateTime UTC"] = pytz.utc.localize(
                    datetime.strptime(result["DateTime UTC"], "%Y-%m-%d %H:%M:%S")
                )
            except (ValueError, TypeError) as e:
                print(f"Error parsing date for match {result.get('MatchId', 'unknown')}: {e}")
                result["DateTime UTC"] = None

        return results

    def get_match(self, match_id: str) -> list[dict]:
        """
        Get a specific match by ID.

        Args:
            match_id: The match ID to query.

        Returns:
            List of match dicts (usually just one, but could be multiple if ID is ambiguous).
        """
        print(f"Getting match: {match_id}")

        # Escape single quotes
        match_id_escaped = match_id.replace("'", "\\'")
        where = f"MS.MatchId = '{match_id_escaped}'"

        results = self.query(
            tables="MatchSchedule=MS, TeamRedirects=TR1, TeamRedirects=TR2",
            fields=(
                "MS.DateTime_UTC, MS.Team1, MS.Team2, MS.Winner, MS.Team1Final, MS.Team2Final, "
                "MS.OverviewPage, MS.MatchId, MS.MatchDay, TR1._pageName=TeamName1, TR2._pageName=TeamName2"
            ),
            where=where,
            join_on="MS.Team1=TR1.AllName, MS.Team2=TR2.AllName",
        )

        # Parse datetime strings
        for result in results:
            try:
                result["DateTime UTC"] = pytz.utc.localize(
                    datetime.strptime(result["DateTime UTC"], "%Y-%m-%d %H:%M:%S")
                )
            except (ValueError, TypeError) as e:
                print(f"Error parsing date for match {match_id}: {e}")
                result["DateTime UTC"] = None

        return results

    def get_matches_by_tournament(self, tournament_name: str) -> list[dict]:
        """
        Get all matches for a specific tournament.

        Args:
            tournament_name: The tournament name (e.g., "Mid-Season Invitational/2024").

        Returns:
            List of match dicts.
        """
        print(f"Getting matches for tournament: {tournament_name}")

        # Escape single quotes
        tournament_escaped = tournament_name.replace("'", "\\'")
        where = f"T.Name = '{tournament_escaped}'"

        results = self.query(
            tables="Tournaments=T, MatchSchedule=MS, TeamRedirects=TR1, TeamRedirects=TR2",
            fields=(
                "T.Name, T.League, T.Year, MS.DateTime_UTC, MS.Team1, MS.Team2, MS.Team1Score, MS.Team2Score, MS.Winner, "
                "MS.OverviewPage, MS.MatchId, MS.MatchDay, TR1._pageName=TeamName1, TR2._pageName=TeamName2"
            ),
            where=where,
            join_on="T.OverviewPage=MS.OverviewPage, MS.Team1=TR1.AllName, MS.Team2=TR2.AllName",
        )

        # Parse datetime strings
        for result in results:
            try:
                result["DateTime UTC"] = pytz.utc.localize(
                    datetime.strptime(result["DateTime UTC"], "%Y-%m-%d %H:%M:%S")
                )
            except (ValueError, TypeError) as e:
                print(f"Error parsing date for match {result.get('MatchId', 'unknown')}: {e}")
                result["DateTime UTC"] = None

        return results
