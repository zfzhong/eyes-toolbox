# build_shutdown_blocks.py
import pandas as pd
from typing import List, Tuple, Optional
from pandas.errors import EmptyDataError


from eyeslib.core.event_block import EventBlock

# Raw event mapping
RAW_SHUTDOWN_EVENTS = {"Device Shutdown", "User Stopped"}
RAW_BOOT_EVENTS     = {"Device Startup", "User Unlocked"}

EventType = str  # "shutdown" or "bootup"


def load_sorted(csv_path: str) -> pd.DataFrame:
    """
    Your preferred loader for shutdown CSVs.
    Uses format='mixed' so it handles both tz-aware/unaware strings.
    """

    try:
        df = pd.read_csv(csv_path)
        df["event_timestamp"] = pd.to_datetime(df["event_timestamp"], format="mixed")
        df = df.sort_values("event_timestamp").reset_index(drop=True)
        return df
    except EmptyDataError:
        return None


def classify_shutdown_event(name: str) -> EventType | None:
    if name in RAW_SHUTDOWN_EVENTS:
        return "shutdown"
    if name in RAW_BOOT_EVENTS:
        return "bootup"
    return None


def glue_shutdown_pairs(events: pd.DataFrame, proximity_seconds: float) -> List[Tuple[pd.Timestamp, EventType]]:
    """
    Minimal 'glue' step for SHUTDOWN side.

    For each row i:
      1) classify as "shutdown"/"bootup"/None
      2) if next row j has same type and within proximity_seconds:
           shutdown pair -> use SECOND timestamp
           bootup   pair -> use FIRST timestamp
         emit one (ts, type) and skip j
      3) otherwise emit (ts_i, type_i)
    """
    if events.empty:
        return []

    events = events.sort_values("event_timestamp").reset_index(drop=True)
    glued: List[Tuple[pd.Timestamp, EventType]] = []
    i = 0
    n = len(events)

    while i < n:
        name_i = events.at[i, "event_name"]
        ts_i   = events.at[i, "event_timestamp"]
        t_i    = classify_shutdown_event(name_i)

        if t_i is None:
            i += 1
            continue

        if i + 1 < n:
            name_j = events.at[i + 1, "event_name"]
            ts_j   = events.at[i + 1, "event_timestamp"]
            t_j    = classify_shutdown_event(name_j)

            if t_j == t_i:
                dt = (ts_j - ts_i).total_seconds()
                if 0 <= dt <= proximity_seconds:
                    if t_i == "shutdown":
                        ts_glue = ts_j  # use SECOND for shutdown pair
                    else:  # "bootup"
                        ts_glue = ts_i  # use FIRST for boot pair
                    glued.append((ts_glue, t_i))
                    i += 2
                    continue

        glued.append((ts_i, t_i))
        i += 1

    return glued


def build_shutdown_blocks_from_glued(
    glued_events: List[Tuple[pd.Timestamp, EventType]]
) -> Optional[EventBlock]:
    """
    Build a linked list of EventBlock(block_type="shutdown") from glued_events.

    - shutdown events become start_ts
    - bootup events become end_ts paired with a pending shutdown if available
    - extra shutdown or bootup generate start_only / end_only blocks
    """
    if not glued_events:
        return None

    head: Optional[EventBlock] = None
    prev: Optional[EventBlock] = None
    pending_shutdown: Optional[pd.Timestamp] = None

    for ts, t in glued_events:
        if t == "shutdown":
            if pending_shutdown is not None:
                # Previous shutdown never got a bootup → start_only block
                blk = EventBlock(block_type=EventBlock.TYPE_SHUTDOWN, start_ts=pending_shutdown, end_ts=None)
                if head is None:
                    head = blk
                if prev is not None:
                    prev.next = blk
                prev = blk
            pending_shutdown = ts

        elif t == "bootup":
            if pending_shutdown is not None and ts >= pending_shutdown:
                blk = EventBlock(block_type=EventBlock.TYPE_SHUTDOWN, start_ts=pending_shutdown, end_ts=ts)
                pending_shutdown = None
                if head is None:
                    head = blk
                if prev is not None:
                    prev.next = blk
                prev = blk
            else:
                # Boot with no shutdown → end_only block
                blk = EventBlock(block_type=EventBlock.TYPE_SHUTDOWN, start_ts=None, end_ts=ts)
                if head is None:
                    head = blk
                if prev is not None:
                    prev.next = blk
                prev = blk

    # leftover pending shutdown
    if pending_shutdown is not None:
        blk = EventBlock(block_type=EventBlock.TYPE_SHUTDOWN, start_ts=pending_shutdown, end_ts=None)
        if head is None:
            head = blk
        if prev is not None:
            prev.next = blk

    return head


def build_shutdown_blocks_from_csv(csv_path: str, proximity_seconds: float) -> Optional[EventBlock]:
    """
    Convenience function used by build_all_blocks.py

    1) load + sort CSV
    2) glue shutdown/bootup pairs within proximity_seconds
    3) build linked list of EventBlock(block_type="shutdown")
    """
    df = load_sorted(csv_path)

    if df is None:
        return None

    glued = glue_shutdown_pairs(df, proximity_seconds)
    head = build_shutdown_blocks_from_glued(glued)
    return head
