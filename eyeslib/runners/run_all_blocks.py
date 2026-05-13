from pathlib import Path
import re
import subprocess
import sys

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:", sys.argv[0], "<dir>")
        sys.exit(1)

    directory = Path(sys.argv[1]+"/processed/segments/")
    csv_files = [f for f in directory.glob("*.csv") if re.search(r'_SHUTDOWN.csv$', f.name)]


    total = len(csv_files)
    for index, c in enumerate(csv_files, start=1):
        file_path = c.parent
        shutdown_filename = c.name

        idle_filename = shutdown_filename.replace("_SHUTDOWN.csv", "_IDLE.csv")
        gap_filename = shutdown_filename.replace("_SHUTDOWN.csv", "_GAP.csv")
        blocks_filename = shutdown_filename.replace("_SHUTDOWN.csv", "_BLOCKS.csv")        

        cmd = [
            sys.executable,
            "-m",
            "eyeslib.segments.build_all_blocks",
            str(c),
            str(file_path / idle_filename),
            str(file_path / gap_filename),
            "60",
            str(file_path / blocks_filename),
        ]
        print(f"[{index}/{total}] {shutdown_filename}")
        print(" ".join(cmd))
        subprocess.run(cmd, check=True)

        
