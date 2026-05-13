from pathlib import Path
import re
import subprocess
import sys

def gen_key(filename):
    tokens = filename.split('_')
    key = "%s_%s" % (tokens[0], tokens[1])
    return key

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:", sys.argv[0], "<raw_dir>")
        sys.exit(1)

    raw_dir = Path(sys.argv[1])
    raw_files = [f for f in raw_dir.glob("*.csv")]

    pickups_dir = Path(sys.argv[1]+'/processed/segments')
    pickups_files = [f for f in pickups_dir.glob("*.csv") if re.search(r'_PICKUPS.csv$', f.name)]

    m = {}
    for c in raw_files:
        filename = c.name
        
        key = gen_key(filename)
        if not key in m:
            m[key] = [c]

    for b in pickups_files:
        filename = b.name
        
        key = gen_key(filename)
        if key in m:
            m[key].append(b)

    total = len(m)
    for index, key in enumerate(m, start=1):
        if not len(m[key]) == 2:
            continue

        raw_file = m[key][0]
        pickups_file = m[key][1]
        
        pickups_filename = pickups_file.name

        tz_filename = pickups_filename.replace("_PICKUPS.csv", "_PICKUPS_tz.csv")  

        cmd = [
            sys.executable,
            "-m",
            "eyeslib.exports.gen_timezone_columns_for_pickups",
            str(raw_file),
            str(pickups_file),
            str(pickups_dir / tz_filename),
        ]
        print(f"[{index}/{total}] {pickups_file.name}")
        print(" ".join(cmd))
        subprocess.run(cmd, check=True)
