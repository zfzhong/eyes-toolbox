"""
This program does 'sorting', 'filtering', and 'splitting' for all 
the csv files (ended with r'\d+\.csv') in the given directory (via argument).
"""

from pathlib import Path
import subprocess
import sys

ARGS = "0 6" # 0: we filter 'Unknown importance: 0', which means no filtering.

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:", sys.argv[0], "<dir>")
        sys.exit(1)

    directory = Path(sys.argv[1])
    csv_files = [f for f in directory.glob("*.csv")]


    total = len(csv_files)
    for index, c in enumerate(csv_files, start=1):
        if c.stat().st_size == 0:
            print(f"[{index}/{total}] {c.name}")
            print(f"Skipping empty raw file: {c}")
            continue

        cmd = [
            sys.executable,
            "-m",
            "eyeslib.preprocess.preprocessing",
            str(c),
            *ARGS.split(),
        ]
        print(f"[{index}/{total}] {c.name}")
        print(" ".join(cmd))
        subprocess.run(cmd, check=True)
