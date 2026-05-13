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
            str(struct_logic),
        ]
        print(f"[{index}/{total}] {c.name}")
        print(" ".join(cmd))
        subprocess.run(cmd, check=True)
