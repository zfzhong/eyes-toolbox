"""
This program does 'sorting', 'filtering', and 'splitting' for all 
the csv files (ended with r'\d+\.csv') in the given directory (via argument).
"""

from pathlib import Path
import re
import subprocess
import sys

ARGS = "2"

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage:", sys.argv[0], "<dir><struct_logic=Y/N>")
        sys.exit(1)

    directory = Path(sys.argv[1]+'/processed')
    csv_files = [f for f in directory.glob("*.csv") if re.search(r'_reordered.csv$', f.name)]
    # Prefer the clean log (background / wake-up chains handled, pattern book B10 / B12) when
    # `make offscreen` has written one.
    csv_files = [f.with_name(f.stem + "_clean.csv") if f.with_name(f.stem + "_clean.csv").exists() else f
                 for f in csv_files]

    struct_logic = False 
    
    if sys.argv[2].capitalize() == 'Y':
        struct_logic = True
    

    total = len(csv_files)
    for index, c in enumerate(csv_files, start=1):
        cmd = [
            sys.executable,
            "-m",
            "eyeslib.usage.chronicle_app_log_parser4",
            str(c),
            ARGS,
            "Y" if struct_logic else "N",   # the parser reads Y/N (passing True/False always meant N)
        ]
        print(f"[{index}/{total}] {c.name}")
        print(" ".join(cmd))
        subprocess.run(cmd, check=True)
