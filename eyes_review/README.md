# eyes_review: local session review

Loads a processed group folder (e.g. `by_group/A1`) into a SQLite database and serves a
review page on `http://127.0.0.1:8877`. Nothing leaves the computer.

```
make review-ingest dir=~/workspace/screen_time/by_group/A1   # once, and after reprocessing
make review                                                  # start the web app
```

The database lives next to the data (`<group>/_review/eyes_review.sqlite`), never in the repo.
Re-ingesting rebuilds everything except the `verdicts` table, which is keyed by
(file stem, session start) so verdicts survive as long as the session is unchanged.

## Flags

A session is put in the review queue when any of these holds (thresholds in `ingest.py`):

| Flag | Rule |
|---|---|
| silence (`gap`) | no event of any kind for >= 3 h inside the session |
| screen off (`idle`) | >= 10 min and >= 50% of the session falls in IDLE |
| long, end inferred (`long_inferred`) | end not observed (screen off, shutdown, end of log) and >= 2 h |

## Verdicts

keep, truncate (at the start of the silence, or at a chosen event), exclude, unsure.
`Export CSV` writes every session with its verdict applied (`reviewed_end_utc`,
`reviewed_duration_s`, `included`).
