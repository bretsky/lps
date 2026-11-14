# analysis/

One-off investigation and debugging scripts. They're kept for reference and aren't part of the
pipeline: nothing in `src/lps/` imports them, and they may go stale as the code changes.

Run them from `backend/`, because some read cwd-relative paths such as `data/cache/` and
`player_yearly_breakdown.json`:

```bash
poetry run python analysis/<script>.py
```

| Script | What it checks |
|---|---|
| `check_faker.py` | Faker's per-year breakdown in `player_yearly_breakdown.json` (written by `career.py`) |
| `check_phase.py` | Phase labels in the cached 2013/2014 Leaguepedia feature pickles (merged vs unmerged) |
| `_faker_probe.py` | Faker's raw Oracle game rows, completeness and win rate for 2014, 2017 and 2018 |
| `_ogn_probe.py` | Leaguepedia page structure for pre-2015 OGN/Champions events |
| `_oracle2014.py` | 2014 Oracle CSV coverage: row counts, leagues, and whether SKT/Faker rows are present |

The `_*.py` probes write their output to `G:/tmp_*.txt`, not stdout.
