from pathlib import Path
import re
import subprocess
import sys

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage:", sys.argv[0], "<dir> <min_duration_seconds> <inter_blocks_seconds>")
        sys.exit(1)

    directory = Path(sys.argv[1]+"/processed/segments")
    min_duration_seconds = int(sys.argv[2])
    inter_block_seconds = int(sys.argv[3])
    
    csv_files = [f for f in directory.glob("*.csv") if re.search(r'_BLOCKS.csv$', f.name)]


    total = len(csv_files)
    for index, c in enumerate(csv_files, start=1):
        file_path = c.parent
        block_filename = c.name

        pickup_filename = block_filename.replace("_BLOCKS.csv", "_PICKUPS.csv")

        cmd = [
            sys.executable,
            "-m",
            "eyeslib.exports.gen_pickups",
            str(c),
            str(min_duration_seconds),
            str(inter_block_seconds),
            str(file_path / pickup_filename),
        ]
        print(f"[{index}/{total}] {block_filename}")
        print(" ".join(cmd))
        subprocess.run(cmd, check=True)
