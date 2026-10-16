# Chains (David, 10-15 / 10-16)

Scripts for the chain method (project doc claude/chain-method-1015.md), run on an A1 category folder
(~/workspace/screen_time/A1/<kids_phone | kids_tablet_android | kids_tablet_fire | parent_phone>) after the pipeline
(`make all eventstz pickupstz dir=<folder>`). Outputs go to <folder>/_review/. Event order only, no time thresholds.

| Script | What it does |
|---|---|
| device_chain2.py | state chains (power cycles): Bootup / LogStart -> ... -> Shutdown / LogEnd; screen repeats mark a chain contradictory |
| state_review_build.py | review list of the contradictions inside state chains -> state_review.json (review app, "State chains" tab) |
| screen_repeats.py | the same contradictions as a CSV |
| chain_logic.py | app triplet chains (Resumed -> Paused -> Stopped), complete / no start / no end / no start-end, where they fail |
| story_cat.py, chain_cover.py, chain_types.py | earlier versions (story checker breaks, time coverage, chains with a 1 s link window - superseded) |

Order: device_chain2.py, then state_review_build.py; review in the app (`make review`, tab State chains).
