# build_all_blocks.py
import sys
from typing import Optional, List

from eyeslib.core.event_block import EventBlock
from eyeslib.core.plot_all_blocks import plot_daily_blocks
from eyeslib.segments.build_shutdown_blocks import build_shutdown_blocks_from_csv
from eyeslib.segments.build_idle_blocks import build_idle_blocks_from_csv
from eyeslib.segments.build_gap_blocks import build_gap_blocks_from_csv
from eyeslib.segments.build_glance_blocks import build_glance_blocks_from_csv


def list_from_linked(head: Optional[EventBlock]) -> List[EventBlock]:
    """
    Helper: convert linked list to a Python list (easier to inspect/merge).
    """
    out: List[EventBlock] = []
    node = head
    while node is not None:
        out.append(node)
        node = node.next
    return out

import pandas as pd
from typing import List

def diff_secs(t1: pd.Timestamp, t2: pd.Timestamp) -> float:
    return abs((t1 - t2).total_seconds())
                   
def reconcile_idle_with_gaps(
    idle_blocks: List[EventBlock],
    gap_blocks: List[EventBlock],
    match_tolerance_seconds: float = 10.0
) -> None:
    s=0
    g=0
    
    while s < len(idle_blocks) and g < len(gap_blocks):
        sblock = idle_blocks[s]

        if sblock.duration_seconds and sblock.duration_seconds <= match_tolerance_seconds:
            s += 1
            continue

        gblock = gap_blocks[g]
        if gblock.duration_seconds and gblock.duration_seconds <= match_tolerance_seconds:
            g += 1
            continue 

        if sblock.start_ts is None:
            if diff_secs(sblock.end_ts, gblock.end_ts) <= match_tolerance_seconds:
                if gblock.block_type == gblock.TYPE_GAP:
                    # update only if this gap block is not matched before (by a shutdown block)
                    gblock.block_type = EventBlock.TYPE_IDLE
                    sblock.start_ts = gblock.start_ts
                s += 1
                g += 1
            elif gblock.end_ts > sblock.end_ts:
                s += 1
            else:
                g += 1
        elif sblock.end_ts is None:
            if diff_secs(sblock.start_ts, gblock.start_ts) <= match_tolerance_seconds:
                if gblock.block_type == gblock.TYPE_GAP:
                    gblock.block_type = EventBlock.TYPE_IDLE
                    sblock.end_ts = gblock.end_ts
                s += 1
                g += 1
            elif gblock.start_ts > sblock.start_ts:
                s += 1
            else:
                g += 1
        else:
            td = pd.Timedelta(seconds=match_tolerance_seconds)
            if gblock.start_ts >= sblock.start_ts - td and gblock.end_ts <= sblock.end_ts + td:
                if gblock.block_type == gblock.TYPE_GAP:
                    gblock.block_type = EventBlock.TYPE_IDLE
                g += 1
            elif gblock.end_ts > sblock.end_ts:
                s += 1
            else:
                g += 1
        

def reconcile_shutdown_with_gaps(
    shutdown_blocks: List[EventBlock],
    gap_blocks: List[EventBlock],
    match_tolerance_seconds: float = 10.0
) -> None:
    s=0
    g=0
    
    while s < len(shutdown_blocks) and g < len(gap_blocks):
        sblock = shutdown_blocks[s]

        if sblock.duration_seconds and sblock.duration_seconds <= match_tolerance_seconds:
            s += 1
            continue

        gblock = gap_blocks[g]
        if gblock.duration_seconds and gblock.duration_seconds <= match_tolerance_seconds:
            g += 1
            continue 

        if sblock.start_ts is None:
            if diff_secs(sblock.end_ts, gblock.end_ts) <= match_tolerance_seconds:
                gblock.block_type = EventBlock.TYPE_SHUTDOWN
                sblock.start_ts = gblock.start_ts
                s += 1
                g += 1
            elif gblock.end_ts > sblock.end_ts:
                s += 1
            else:
                g += 1
        elif sblock.end_ts is None:
            if diff_secs(sblock.start_ts, gblock.start_ts) <= match_tolerance_seconds:
                gblock.block_type = EventBlock.TYPE_SHUTDOWN
                sblock.end_ts = gblock.end_ts
                s += 1
                g += 1
            elif gblock.start_ts > sblock.start_ts:
                s += 1
            else:
                g += 1
        else:
            td = pd.Timedelta(seconds=match_tolerance_seconds)
            if gblock.start_ts >= sblock.start_ts - td and gblock.end_ts <= sblock.end_ts + td:
                gblock.block_type = EventBlock.TYPE_SHUTDOWN
                g += 1
            elif gblock.end_ts > sblock.end_ts:
                s += 1
            else:
                g += 1

def exclude_shutdown_from_idle_blocks(
        idle_blocks: List[EventBlock],
        shutdown_blocks: List[EventBlock]
):
    i = 0
    block_list = []

    for b in idle_blocks:
        if b.duration_seconds is None:
            continue

        if b.block_type != EventBlock.TYPE_IDLE:
            continue

        while i < len(shutdown_blocks):
            if not shutdown_blocks[i].duration_seconds:
                i += 1
                continue
            
            if shutdown_blocks[i].end_ts > b.end_ts:
                break

            # process all shutdown blocks that fall into the interval of this Idle block.
            sblock = shutdown_blocks[i]
            
            if sblock.duration_seconds and sblock.end_ts > b.start_ts:
                if sblock.start_ts >= b.start_ts:
                    # create a new idle block
                    new_iblock = EventBlock(EventBlock.TYPE_IDLE, start_ts=b.start_ts, end_ts=sblock.start_ts)
                    #print("new block", new_iblock.start_ts, new_iblock.end_ts)
                    block_list.append(new_iblock)

                    # update the start_ts of the current idle block
                    b.start_ts = sblock.end_ts
                else:
                    print("Idle/Shutdown start_ts logic warning: Shutdown happen before Idle.")
                    print(b.start_ts,b.end_ts,sblock.start_ts,sblock.end_ts)

                    # This did happen in data file '4562_C01'
                    if sblock.end_ts < b.end_ts:
                        b.start_ts = sblock.end_ts
                    else:
                        # set the block type and ignore this block
                        b.block_type = EventBlock.TYPE_SHUTDOWN
            
            i += 1
        
        block_list.append(b)

    return block_list


def exclude_overlapping_blocks(
        blocks: List[EventBlock],
        disallowed_blocks: List[EventBlock],
        tolerance_seconds: float = 0.0,
):
    if not blocks:
        return []

    valid_disallowed = [
        b for b in disallowed_blocks
        if b.start_ts is not None and b.end_ts is not None and b.duration_seconds is not None
    ]
    if not valid_disallowed:
        return blocks

    valid_disallowed = sorted(valid_disallowed, key=lambda b: b.start_ts)
    td = pd.Timedelta(seconds=tolerance_seconds)

    filtered_blocks = []
    j = 0
    for block in blocks:
        if block.start_ts is None or block.end_ts is None or block.duration_seconds is None:
            continue

        while j < len(valid_disallowed) and valid_disallowed[j].end_ts <= block.start_ts - td:
            j += 1

        k = j
        has_overlap = False
        while k < len(valid_disallowed) and valid_disallowed[k].start_ts < block.end_ts + td:
            other = valid_disallowed[k]
            if other.end_ts > block.start_ts - td and other.start_ts < block.end_ts + td:
                has_overlap = True
                break
            k += 1

        if not has_overlap:
            filtered_blocks.append(block)

    return filtered_blocks


def dump_blocks(shutdown_blocks, idle_blocks, glance_blocks, gap_blocks, blocks_out_csv):
    """
    Dump all blocks that has a duration >= proximity_seconds.

    In theory, if a block has duration less than the 'proximity_seconds', that means this block
    is within the error margin.
    """

    f = open(blocks_out_csv, 'w')
    f.write("start_ts,end_ts,duration_seconds,block_type\n")
    for b in shutdown_blocks:
        f.write("%s,%s,%s,%s\n" % (b.start_ts, b.end_ts, b.duration_seconds, b.block_type))

    for b in idle_blocks:
        if b.block_type == EventBlock.TYPE_IDLE:
            f.write("%s,%s,%s,%s\n" % (b.start_ts, b.end_ts, b.duration_seconds, b.block_type))

    for b in glance_blocks:
        if b.block_type == EventBlock.TYPE_GLANCE:
            f.write("%s,%s,%s,%s\n" % (b.start_ts, b.end_ts, b.duration_seconds, b.block_type))

    for b in gap_blocks:
        if b.block_type == EventBlock.TYPE_GAP:
            f.write("%s,%s,%s,%s\n" % (b.start_ts, b.end_ts, b.duration_seconds, b.block_type))
    f.close()

def main():
    if len(sys.argv) < 6:
        print("Usage: python build_all_blocks.py shutdown.csv idle.csv gap.csv proximity_seconds blocks.csv [activity.csv]")
        print("  activity.csv: the *_reordered.csv log; its app foreground events are used by GLANCE detection.")
        sys.exit(1)

    shutdown_csv = sys.argv[1]
    idle_csv     = sys.argv[2]
    gap_csv      = sys.argv[3]
    proximity_seconds  = float(sys.argv[4])
    blocks_out_csv = sys.argv[5]
    activity_csv   = sys.argv[6] if len(sys.argv) > 6 else None
    if activity_csv is None:
        print("[WARN] no activity log given: GLANCE uses Keyguard Hidden only (no foreground-app evidence)")

    shutdown_head = build_shutdown_blocks_from_csv(shutdown_csv, proximity_seconds)
    idle_head     = build_idle_blocks_from_csv(idle_csv, proximity_seconds)
    gap_head      = build_gap_blocks_from_csv(gap_csv)
    glance_head   = build_glance_blocks_from_csv(idle_csv, shutdown_csv, gap_csv, activity_csv)


    shutdown_blocks = list_from_linked(shutdown_head) or []
    idle_blocks     = list_from_linked(idle_head) or []
    gap_blocks      = list_from_linked(gap_head) or []
    glance_blocks   = list_from_linked(glance_head) or []

    #print("=== SHUTDOWN BLOCKS ===")
    #for b in shutdown_blocks:
    #    print(f"[{b.block_type}/{b.kind}] {b.start_ts} -> {b.end_ts} (dur={b.duration_seconds})")

    #print("\n=== IDLE BLOCKS ===")
    #for b in idle_blocks:
    #    print(f"[{b.block_type}/{b.kind}] {b.start_ts} -> {b.end_ts} (dur={b.duration_seconds})")

    reconcile_shutdown_with_gaps(shutdown_blocks, gap_blocks)
    #print("-----")
    reconcile_idle_with_gaps(idle_blocks, gap_blocks)

    #print("=== RECONCILED SHUTDOWN BLOCKS ===")
    #for b in shutdown_blocks:
    #    print(f"[{b.block_type}/{b.kind}] {b.start_ts} -> {b.end_ts} (dur={b.duration_seconds})")

    #print("\n=== RECONCILED IDLE BLOCKS ===")
    #for b in idle_blocks:
    #    print(f"[{b.block_type}/{b.kind}] {b.start_ts} -> {b.end_ts} (dur={b.duration_seconds})")

    #print("\n=== RECONCILED GAP BLOCKS ===")
    #for b in gap_blocks:
    #    print(f"[{b.block_type}/{b.kind}] {b.start_ts} -> {b.end_ts} (dur={b.duration_seconds})")

    new_idle_blocks = exclude_shutdown_from_idle_blocks(idle_blocks, shutdown_blocks)
    active_gap_blocks = [b for b in gap_blocks if b.block_type == EventBlock.TYPE_GAP]
    glance_blocks = exclude_overlapping_blocks(glance_blocks, shutdown_blocks + active_gap_blocks)

    # if we want to visualize the blocks, we uncomment the following line
    #plot_daily_blocks(shutdown_blocks, new_idle_blocks, active_gap_blocks, out_png=out_png_file)

    dump_blocks(shutdown_blocks, new_idle_blocks, glance_blocks, gap_blocks, blocks_out_csv)


if __name__ == "__main__":
    main()
