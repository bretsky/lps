# CLR: League of Legends all-time rankings

**Live site: [clr.brettselby.xyz](https://clr.brettselby.xyz)** (English · 한국어 · 简体中文)

An all-time ranking of professional League of Legends players, built game by game from 2011 to
today. Every pro game a player has played is scored by how much their own play moved their team's
chance of winning, adjusted for the strength of the opposition and the stakes of the match. Those
scores add up into a season rating (**LPS**, League Performance Score) and then into a career rating
(**CLR**, Career Legend Rating) that weighs longevity, rate, peak and trophies.

The idea borrows from baseball's WAR and JAWS and hockey's Pidutti Point Share: one number per
career, on a scale where seasons compare directly across eras, regions and roles.

## How the score works

1. **Contribution.** Two models are trained on each season's pro games. One predicts the stat line
   (kills, deaths, assists, damage) an average player would produce in the same role and game
   situation; the other predicts a team's chance of winning from what its players actually
   produced. A player's contribution in a game is how much that predicted win chance changes when
   their expected stat line is swapped for their real one.
2. **Game score.** Each game earns a win credit, the player's contribution, and a bonus for beating
   the odds, all multiplied by a **region factor** for the strength of the opposing league.
3. **Regional strength** comes from an Elo system run over every international event (Worlds, MSI,
   First Stand, IEM and others) year by year, so a game against an LCK team is worth more than the
   same game against a weaker league.
4. **Season LPS** adds the matches up, with playoffs and international events counting for more.
5. **CLR** combines four parts: career value (total LPS, era-adjusted, scaled to a typical career),
   pace value (LPS per season, shrunk toward average for short careers), peak value (the best
   stretch of seasons), and a **résumé** of fixed points for titles, deep international runs and
   awards.

The site's [About page](https://clr.brettselby.xyz/about) defines every number in full, with the
exact weights and point tables. [`docs/holistic-lps-plan.md`](docs/holistic-lps-plan.md) has the
design reasoning behind CLR.

## Repository layout

| Folder | What it is |
|---|---|
| [`backend/`](backend/) | Python 3.12 (Poetry). Data ingestion, the win-probability and expected-performance models, regional Elo, and the pipeline that writes per-season and career workbooks plus the site's JSON bundle. See [`backend/README.md`](backend/README.md). |
| [`frontend/`](frontend/) | The website: Next.js 15, React 19, TypeScript and Tailwind, exported as a fully static site. |
| [`docs/`](docs/) | Design notes: the CLR plan, the website plan and the roadmap. |
| [`CLAUDE.md`](CLAUDE.md) | Contributor notes on how the pieces fit together and the non-obvious gotchas. |

The hand-curated inputs (team-to-region mappings per year, Elo seeds and results, identity fixes
for players who share a handle) live in `backend/info/` and are committed. Raw match data and
caches (`backend/data/`) are not; the pipeline downloads them.

## Running the site locally

The current data bundle is committed in `frontend/public/data/current/`, so the site runs without
the backend:

```bash
cd frontend
npm install
npm run dev
```

Then open <http://localhost:3000>.

## Running the pipeline

```bash
cd backend
poetry install
cp .env.example .env          # add Leaguepedia bot credentials (see backend/README.md)
poetry run python -m lps.update_all --dry-run    # show the plan
poetry run python -m lps.update_all              # refresh the latest season end to end
```

`update_all` pulls the latest Oracle's Elixir and Leaguepedia data, recomputes regional Elo,
rebuilds every season's scores and the career ranking, and writes the site bundle. The full set of
steps, flags and the yearly rollover are in [`backend/README.md`](backend/README.md).

## Data sources and credits

- **[Oracle's Elixir](https://oracleselixir.com/)** for game-level box scores from 2014 on.
- **[Leaguepedia](https://lol.fandom.com/)** for 2011–13 games (and gaps in the 2014–15 Eastern
  leagues), international results, rosters,
  titles, awards and player photos. Leaguepedia content is licensed
  [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/).
- **[Data Dragon](https://developer.riotgames.com/docs/lol#data-dragon)** for champion icons.

CLR isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games or anyone
officially involved in producing or managing Riot Games properties. Riot Games and all associated
properties are trademarks or registered trademarks of Riot Games, Inc. League and team marks
belong to their owners.

## License

The code is released under the [MIT License](LICENSE). The data under `frontend/public/data/` and
`backend/info/` is derived from the sources above and remains subject to their terms.
