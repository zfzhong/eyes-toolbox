from pathlib import Path
import subprocess
import sys

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage:", sys.argv[0], "<chronicle_log_dir>")
        sys.exit(1)

    directory = Path(sys.argv[1]+'/processed')
    min_hours = 3


    csv_files = [f for f in directory.glob("*_reordered.csv")]

    total = len(csv_files)
    for index, infile in enumerate(csv_files, start=1):
        dir_name = infile.parent
        file_name = infile.name

        tokens = file_name.split('.')

        prefix = tokens[0].replace(' ', '_')
        outfile = dir_name / "segments" / f"{prefix}_GAP.csv"

        cmd = [
            sys.executable,
            "-m",
            "eyeslib.segments.identify_gap_segments",
            str(infile),
            str(min_hours),
            str(outfile),
        ]
        print(f"[{index}/{total}] {file_name}")
        print(" ".join(cmd))
        subprocess.run(cmd, check=True)
