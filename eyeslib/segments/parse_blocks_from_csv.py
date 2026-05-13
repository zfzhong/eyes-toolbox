from eyeslib.core.blocks_from_csv import build_blocks_from_csv

import sys

def main():
    if len(sys.argv) < 3:
        print("Usage: python %s blocks.csv min_duration_seconds" % sys.argv[0])
        sys.exit(1)

    block_csv_filename = sys.argv[1]
    min_duration_seconds = int(sys.argv[2])

    blocks = build_blocks_from_csv(block_csv_filename)

    for b in blocks:
        print(b)

if __name__ == "__main__":
    main()
