"""Build app-usage sessions for every reordered log in <dir>/processed.

Writes <dir>/processed/sessions/<stem>_SESSION.csv and <stem>_SESSION_APPS.csv.
"""
from pathlib import Path
import subprocess
import sys

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage:", sys.argv[0], "<dir>")
        sys.exit(1)

    directory = Path(sys.argv[1] + "/processed")
    csv_files = sorted(directory.glob("*_reordered.csv"))
    out_dir = directory / "sessions"

    total = len(csv_files)
    for index, infile in enumerate(csv_files, start=1):
        cmd = [sys.executable, "-m", "eyeslib.usage.build_sessions", str(infile), str(out_dir)]
        print(f"[{index}/{total}] {infile.name}")
        print(" ".join(cmd))
        subprocess.run(cmd, check=True)
