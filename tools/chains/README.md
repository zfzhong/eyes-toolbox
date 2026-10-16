# Chains (David, 10-15 / 10-16)

Scripts for the chain method (project doc claude/chain-method-1015.md), run on an A1 category folder
(~/workspace/screen_time/A1/<kids_phone | kids_tablet_android | kids_tablet_fire | parent_phone>) after the pipeline
(`make all eventstz pickupstz dir=<folder>`). Outputs go to <folder>/_review/. Event order only, no time thresholds.

| Script | What it does |
|---|---|
| power_cycles.py | divides each file into Power Cycles: Bootup / LogStart -> ... -> Shutdown / LogEnd; two screen-ons or two screen-offs in a row make a Power Cycle contradictory |
| device_chain2.py | the same, earlier name (superseded by power_cycles.py) |
| state_review_build.py | review list of the contradictions inside Power Cycles -> state_review.json (review app, "Power cycles" tab) |
| screen_repeats.py | the same contradictions as a CSV |
| chain_logic.py | app triplet chains (Resumed -> Paused -> Stopped), complete / no start / no end / no start-end, where they fail |
| story_cat.py, chain_cover.py, chain_types.py | earlier versions (story checker breaks, time coverage, chains with a 1 s link window - superseded) |

Order: power_cycles.py, then state_review_build.py; review in the app (`make review`, tab Power cycles).

Terms (David, 10-16): file -> Power Cycles (Bootup or LogStart ... Shutdown or LogEnd; only Bootup / Shutdown are power-on / power-off) -> screen sessions -> triplets (Resumed -> Paused -> Stopped) -> app chains.
