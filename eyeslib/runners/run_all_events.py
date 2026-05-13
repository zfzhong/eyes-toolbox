from pathlib import Path
import subprocess
import sys

def gen_key(filename):
    tokens = filename.split('_')
    key = "%s_%s" % (tokens[0], tokens[1])
    return key


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage:", sys.argv[0], "<chronicle_log_dir>")
        sys.exit(1)

    directory = Path(sys.argv[1]+'/processed')

    chronicle_files = [f for f in directory.glob("*_uniq.csv")]
    secondary_files = [f for f in directory.glob("*_primary_secondary_fau.csv")]


    m = {}
    for c in chronicle_files:
        filename = c.name
        
        key = gen_key(filename)
        if not key in m:
            m[key] = [c]

    for b in secondary_files:
        filename = b.name
        
        key = gen_key(filename)
        if key in m:
            m[key].append(b)

    total = len(m)
    for index, key in enumerate(m, start=1):
        chronicle_file = m[key][0]
        secondary_file = m[key][1]
        output_file = directory / f"{key}_events.csv"

        cmd = [
            sys.executable,
            "-m",
            "eyeslib.exports.gen_all_events",
            str(chronicle_file),
            str(secondary_file),
            str(output_file),
        ]
        print(f"[{index}/{total}] {chronicle_file.name}")
        print(" ".join(cmd))
        subprocess.run(cmd, check=True)
