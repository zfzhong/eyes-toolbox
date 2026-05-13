import pandas as pd
from pandas.errors import EmptyDataError

from typing import Optional
from eyeslib.core.event_block import EventBlock


GAP_START = "Gap Start"
GAP_END   = "Gap End"


def build_gap_blocks_from_csv(csv_path: str) -> Optional[EventBlock]:
    """
    Build a linked list of EventBlock(block_type='gap') from a GAP CSV file.

    The CSV must contain:
        - event_name        (values: "gap start", "gap end")
        - event_timestamp   (timestamp for each event)

    Assumptions:
        - Events are well-formed: each "gap start" is followed by a "gap end".
        - Input is already sorted in time, but we sort again to be safe.

    Returns:
        head of linked list of EventBlock, or None if no gaps found.
    """
    try:
        df = pd.read_csv(csv_path)
    except EmptyDataError:
        return None

    if "event_name" not in df.columns or "event_timestamp" not in df.columns:
        raise ValueError("GAP CSV must include 'event_name' and 'event_timestamp' columns.")

    # Parse timestamps
    df["event_timestamp"] = pd.to_datetime(df["event_timestamp"], format="mixed", errors="coerce")
    df = df.dropna(subset=["event_timestamp"])

    # Keep only gap start / gap end rows
    df = df[df["event_name"].isin([GAP_START, GAP_END])]
    if df.empty:
        return None

    # Build blocks
    head: Optional[EventBlock] = None
    prev: Optional[EventBlock] = None
    pending_start: Optional[pd.Timestamp] = None

    for _, row in df.iterrows():
        name = row["event_name"]
        ts   = row["event_timestamp"]

        if name == GAP_START:
            pending_start = ts

        elif name == GAP_END:
            if pending_start is None:
                print("[WARN] GAP end without preceding GAP start:", ts)
                continue

            if ts <= pending_start:
                print("[WARN] GAP end <= GAP start; ignoring interval:", pending_start, ts)
                pending_start = None
                continue

            blk = EventBlock(
                block_type=EventBlock.TYPE_GAP,
                start_ts=pending_start,
                end_ts=ts,
                next=None,
            )

            if head is None:
                head = blk
            if prev is not None:
                prev.next = blk
            prev = blk

            pending_start = None

    # Handle unexpected dangling start
    if pending_start is not None:
        print("[WARN] Last GAP start has no GAP end; start_ts =", pending_start)

    return head
