"""Label app events in confirmed screen-off periods (background / wake-up chains) for every
*_reordered.csv in <dir>/processed, and write <stem>_offscreen.csv and <stem>_clean.csv.
See eyeslib/states/offscreen_chains.py and pattern book B10 / B12."""
from pathlib import Path
import sys

from eyeslib.states.offscreen_chains import main

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage:", sys.argv[0], "<dir>"); sys.exit(1)
    files = sorted(Path(sys.argv[1] + "/processed").glob("*_reordered.csv"))
    main(files)
