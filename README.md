# EYES Toolbox

EYES is a Chronicle Android activity-log processing toolbox. It can be run from
the command line with `make`, or through the desktop GUI for users who want to
choose a raw-data folder and click `Go`.

## Install

From the repository root:

```sh
python -m pip install -e .
```

Tkinter is used for the GUI and is included with many Python distributions. If
your Python install does not include Tkinter, install the Tk package for that
Python distribution first.

## GUI Launcher

Launch the desktop toolbox after installation with:

```sh
eyes-toolbox
```

or from the repository root with:

```sh
make gui
```

or:

```sh
python -m eyeslib.gui.app
```

The GUI lets a user:

- choose a folder containing raw Chronicle CSV files
- click `Go`
- run the full toolbox pipeline from preprocessing through plots, pickups, and timezone exports
- watch progress and logs in one window

## Repository Layout

Implementation code lives under:

- `eyeslib/core`: shared block models and plotting helpers
- `eyeslib/preprocess`: raw Chronicle preprocessing steps
- `eyeslib/segments`: shutdown, idle, gap, and glance detection
- `eyeslib/usage`: app/activity parsing and usage derivation
- `eyeslib/exports`: final event, pickup, timezone, and FAU exports
- `eyeslib/runners`: batch entrypoints used by the Makefile
- `eyeslib/gui`: desktop toolbox launcher

The top-level `*.py` files are compatibility wrappers so older commands still
work. New code should be added under `eyeslib`.

## Main Workflow

Run from the repository root with a Chronicle raw folder passed as `dir`:

```sh
make all dir=/path/to/raw/stopped
```

Available stages:

- `make preprocess dir=...`
- `make uniq dir=...`
- `make reorder dir=...`
- `make gap dir=...`
- `make shutdown dir=...`
- `make idle dir=...`
- `make blocks dir=...`
- `make sessions dir=...` (app-usage sessions and trigger chains, see "Sessions" in the manual)
- `make parser dir=...`
- `make app dir=...`
- `make nest dir=...`
- `make merge dir=...`
- `make fau dir=...`
- `make pickups dir=...`
- `make pickupstz dir=...`
- `make allevents dir=...`
- `make eventstz dir=...`
- `make visual dir=...`
- `make gui`

The `blocks` stage now includes `GLANCE` alongside `SHUTDOWN`, `IDLE`, and `GAP`.

## Direct Module Entry

The Makefile uses module entrypoints, for example:

```sh
python -m eyeslib.runners.run_all_blocks /path/to/raw/stopped
python -m eyeslib.runners.run_parser4 /path/to/raw/stopped Y
python -m eyeslib.usage.visualize_app_usage /path/to/raw/stopped
```

## Notes

- `ACTIVE` is the complement of `SHUTDOWN`, `IDLE`, `GAP`, and `GLANCE`.
- `GLANCE` captures wake sessions (`Screen Interactive` → `Screen Non-interactive`) with no evidence of use: no `Keyguard Hidden` event and less than 5 s of non-system app foreground time. See "Glance Logic" in the manual.
- The full user manual is in `docs/eyes-manual.pdf`; the LaTeX source is in `docs/eyes-manual.tex`.
