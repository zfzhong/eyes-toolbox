from pathlib import Path
import re
import subprocess
import sys

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:", sys.argv[0], "<dir>")
        sys.exit(1)

    directory = Path(sys.argv[1]+'/processed')
    csv_files = [f for f in directory.glob("*.csv") if re.search(r'_primary_secondary_fau.csv$', f.name)]


    total = len(csv_files)
    for index, c in enumerate(csv_files, start=1):
        file_path = c.parent
        file_name = c.name
        
        outfile = file_name.replace("_primary_secondary_fau.csv", "_fau_usage.csv")
        cmd = [
            sys.executable,
            "-m",
            "eyeslib.exports.gen_fau_screen_time",
            str(c),
            "--statuses",
            "ACTIVE",
            "--mode",
            "primary",
            "--output",
            str(file_path / outfile),
        ]
        
        print(f"[{index}/{total}] {file_name}")
        print(" ".join(cmd))
        subprocess.run(cmd, check=True)

