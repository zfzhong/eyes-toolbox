# build_idle_blocks.py
import pandas as pd
from typing import List, Tuple, Optional
from pandas.errors import EmptyDataError

from eyeslib.core.event_block import EventBlock

IDLE_START_EVENTS = {"Screen Non-interactive", "Keyguard Shown"}
IDLE_END_EVENTS   = {"Screen Interactive", "Keyguard Hidden"}

IdleEventType = str  # "start" or "end"


def load_sorted(csv_path: str) -> pd.DataFrame:
    try:
        df = pd.read_csv(csv_path)
        df["event_timestamp"] = pd.to_datetime(df["event_timestamp"], format="mixed")
        df = df.sort_values("event_timestamp").reset_index(drop=True)
        return df
    except EmptyDataError:
        return None


def classify_idle_event(name: str) -> IdleEventType | None:
    if name in IDLE_START_EVENTS:
        return "start"
    if name in IDLE_END_EVENTS:
        return "end"
    return None


def glue_idle_pairs(events: pd.DataFrame, proximity_seconds: float) -> List[Tuple[pd.Timestamp, IdleEventType]]:
    """
    Same idea as glue_shutdown_pairs, but for idle events.

    - start-start within gap → use SECOND timestamp
    - end-end   within gap → use FIRST timestamp
    """
    if events.empty:
        return []

    events = events.sort_values("event_timestamp").reset_index(drop=True)
    glued: List[Tuple[pd.Timestamp, IdleEventType]] = []
    i = 0
    n = len(events)

    while i < n:
        name_i = events.at[i, "event_name"]
        ts_i   = events.at[i, "event_timestamp"]
        t_i    = classify_idle_event(name_i)

        if t_i is None:
            i += 1
            continue

        if i + 1 < n:
            name_j = events.at[i + 1, "event_name"]
            ts_j   = events.at[i + 1, "event_timestamp"]
            t_j    = classify_idle_event(name_j)

            if t_j == t_i:
                dt = (ts_j - ts_i).total_seconds()
                if 0 <= dt <= proximity_seconds:
                    if t_i == "start":
                        ts_glue = ts_j   # start-start → use second
                    else:  # "end"
                        ts_glue = ts_i   # end-end → use first
                    glued.append((ts_glue, t_i))
                    i += 2
                    continue

        glued.append((ts_i, t_i))
        i += 1

    return glued


def build_idle_blocks_from_glued(
    glued_events: List[Tuple[pd.Timestamp, IdleEventType]]
) -> Optional[EventBlock]:
    """
    Build linked list of EventBlock(block_type="idle") from glued idle events.
    """
    if not glued_events:
        return None

    head: Optional[EventBlock] = None
    prev: Optional[EventBlock] = None
    pending_start: Optional[pd.Timestamp] = None

    for ts, t in glued_events:
        if t == "start":
            if pending_start is not None:
                blk = EventBlock(block_type=EventBlock.TYPE_IDLE, start_ts=pending_start, end_ts=None)
                if head is None:
                    head = blk
                if prev is not None:
                    prev.next = blk
                prev = blk
            pending_start = ts

        elif t == "end":
            if pending_start is not None and ts > pending_start:
                blk = EventBlock(block_type=EventBlock.TYPE_IDLE, start_ts=pending_start, end_ts=ts)
                pending_start = None
                if head is None:
                    head = blk
                if prev is not None:
                    prev.next = blk
                prev = blk
            else:
                blk = EventBlock(block_type=EventBlock.TYPE_IDLE, start_ts=None, end_ts=ts)
                if head is None:
                    head = blk
                if prev is not None:
                    prev.next = blk
                prev = blk

    if pending_start is not None:
        blk = EventBlock(block_type=EventBlock.TYPE_IDLE, start_ts=pending_start, end_ts=None)
        if head is None:
            head = blk
        if prev is not None:
            prev.next = blk

    return head


def build_idle_blocks_from_csv(csv_path: str, proximity_seconds: float) -> Optional[EventBlock]:
    df = load_sorted(csv_path)

    if df is None:
        return None

    glued = glue_idle_pairs(df, proximity_seconds)
    head = build_idle_blocks_from_glued(glued)
    return head
