from typing import List
import pandas as pd

from eyeslib.core.blocks_from_csv import build_blocks_from_csv
from eyeslib.core.event_block import EventBlock


def merge_connected_blocks(
    blocks: List[EventBlock],
    tolerance_seconds: float = 0.0,
) -> List[EventBlock]:
    """
    Merge consecutive blocks when they are connected in time:
        prev.end_ts == next.start_ts  (or within tolerance_seconds)

    Unlike the prior version, block_type does NOT need to match.
    If types differ, the merged block_type becomes `mixed_type` (default "MIXED").

    Assumptions:
      - blocks are paired (start_ts/end_ts exist)
      - blocks are sorted by start_ts
      - blocks do not overlap (only touch or are disjoint)
    """

    if not blocks:
        return []

    tol = pd.Timedelta(seconds=tolerance_seconds)

    merged: List[EventBlock] = []
    cur = blocks[0]

    for b in blocks[1:]:
        # If connected (touching within tolerance), merge
        if abs(b.start_ts - cur.end_ts) <= tol:
            # extend end
            if b.end_ts > cur.end_ts:
                cur.end_ts = b.end_ts

            # update type
            if cur.block_type != b.block_type:
                cur.block_type = EventBlock.TYPE_MIXED
            # if already same, keep it
        else:
            merged.append(cur)
            cur = b

    merged.append(cur)
    return merged

def fill_active_blocks(
        blocks: List[EventBlock],
        tolerance_seconds: float = 0.0,
    ) -> List[EventBlock]:
    """
    Insert ACTIVE blocks into the uncovered time between non-active blocks.

    Blocks are sorted by start_ts but may overlap (e.g. a short GAP inside a
    long IDLE), so the uncovered time starts at the latest end_ts seen so far,
    not at the end of the immediately preceding block.
    """
    if not blocks: return []

    tol = pd.Timedelta(seconds=tolerance_seconds)
    block_list: List[EventBlock] = [blocks[0]]
    covered_until = blocks[0].end_ts

    for b in blocks[1:]:
        if b.start_ts - covered_until >= tol:
            block_list.append(EventBlock(EventBlock.TYPE_ACTIVE, covered_until, b.start_ts))
        block_list.append(b)
        if b.end_ts > covered_until:
            covered_until = b.end_ts

    return block_list






import sys

def main():
    if len(sys.argv) < 5:
        print("Usage: python %s blocks.csv min_duration_seconds inter_blocks_seconds out_pickups.csv" % sys.argv[0])
        sys.exit(1)

    block_csv_filename = sys.argv[1]
    min_duration_seconds = int(sys.argv[2])
    tolerance_seconds = int(sys.argv[3])
    pickups_csv_filename = sys.argv[4]

    blocks = build_blocks_from_csv(block_csv_filename)
    list_blocks = fill_active_blocks(blocks, tolerance_seconds)

    f = open(pickups_csv_filename, 'w')
    f.write("start_ts,end_ts,duration_seconds,block_type\n")
    for b in list_blocks:
        if b.duration_seconds >= min_duration_seconds:
            f.write("%s,%s,%s,%s\n" % (b.start_ts, b.end_ts, b.duration_seconds, b.block_type))
    f.close()
        

if __name__ == "__main__":
    main()
