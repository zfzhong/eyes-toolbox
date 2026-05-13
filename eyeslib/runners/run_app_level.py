from pathlib import Path
import re
import subprocess
import sys

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:", sys.argv[0], "<dir>")
        sys.exit(1)

    directory = Path(sys.argv[1]+'/processed')
    csv_files = [f for f in directory.glob("*.csv") if re.search(r'reordered_act_one.csv$', f.name)]


    total = len(csv_files)
    for index, c in enumerate(csv_files, start=1):
        file_path = c.parent
        file_name = c.name
        
        tokens = file_name.split("_")

        outfile = f"{tokens[0]}_{tokens[1]}_app_1.csv"
        cmd = [
            sys.executable,
            "-m",
            "eyeslib.usage.get_app_screen_time",
            str(c),
        ]
        print(f"[{index}/{total}] {file_name}")
        print(" ".join(cmd), ">", file_path / outfile)
        with (file_path / outfile).open("w", encoding="utf-8") as output_handle:
            subprocess.run(cmd, check=True, stdout=output_handle)

