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
        print("Usage:", sys.argv[0], "<app_chunk_dir>")
        sys.exit(1)

    chunk_dir = Path(sys.argv[1]+'/processed')
    chunk_files = [f for f in chunk_dir.glob("*.csv") if re.search(r'_nested.csv$', f.name)]

    block_dir = Path(sys.argv[1]+"/processed/segments/")
    block_files = [f for f in block_dir.glob("*.csv") if re.search(r'_BLOCKS.csv$', f.name)]

    m = {}
    for c in chunk_files:
        filename = c.name
        
        key = gen_key(filename)
        if not key in m:
            m[key] = [c]

    for b in block_files:
        filename = b.name
        
        key = gen_key(filename)
        if key in m:
            m[key].append(b)

    total = len(m)
    for index, key in enumerate(m, start=1):
        chunk_file = m[key][0]
        block_file = m[key][1]
        threshold = 5 # block minimum duration >= 5 seconds 

        cmd = [
            sys.executable,
            "-m",
            "eyeslib.usage.merge_app_status",
            str(chunk_file),
            str(block_file),
            str(threshold),
        ]
        print(f"[{index}/{total}] {chunk_file.name}")
        print(" ".join(cmd))
        subprocess.run(cmd, check=True)

