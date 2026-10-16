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

## EventLost blocks (10-16)
David: not "Unknown", "since we know something: some events (likely Paused) are lost". Where the log contradicts itself,
screen_blocks.py writes a **EventLost** block whose column `lost` lists the events that must be missing:
two Screen Interactive -> Screen Non-interactive (+ Paused/Stopped of the app still in front); two Screen Non-interactive ->
Screen Interactive (+ Resumed of an app whose chain begins with Paused); a boot signature inside adds "or Device Shutdown + Bootup".
"Unknown" remains only before logging began (LogStart, before the first screen event).
David (10-16, 15:06): "I think we should use 'EventLost', and this 'EventLost' will serve as the end of a activity chain".
An app chain that cannot end properly ends with EventLost at its last evidence (two Screen Interactive); in the mirror case
(two Screen Non-interactive) the chain begins with EventLost. start_by / end_by of the ScreenOn block say EventLost.
