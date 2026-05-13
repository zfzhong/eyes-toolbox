import sys
from pathlib import Path

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage:", sys.argv[0], "<chronicle_sortedfile_dir>")
        sys.exit(1)

    directory = Path(sys.argv[1]+'/processed')

    csv_files = [f for f in directory.glob("*_sorted.csv")]

    total = len(csv_files)
    for index, infile in enumerate(csv_files, start=1):
        dir_name = infile.parent
        file_name = infile.name
        tokens = file_name.split('.')

        prefix = tokens[0].replace(' ', '_')
        outfile = dir_name / f"{prefix}_uniq.csv"

        print(f"[{index}/{total}] {infile.name}")
        print(f"uniq {infile} > {outfile}")
        previous_line = None
        with infile.open("r", encoding="utf-8", errors="replace") as src, outfile.open(
            "w", encoding="utf-8"
        ) as dst:
            for line in src:
                if line != previous_line:
                    dst.write(line)
                previous_line = line
