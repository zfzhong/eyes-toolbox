import pandas as pd
from pandas.errors import EmptyDataError

from typing import Optional

from eyeslib.core.event_block import EventBlock


GLANCE_START_EVENT = "Screen Interactive"
GLANCE_END_EVENT = "Screen Non-interactive"
UNLOCK_EVENT = "Keyguard Hidden"
CANCEL_EVENTS = {"Device Shutdown", "User Stopped", "Gap Start"}


def load_event_slice(csv_path: str) -> Optional[pd.DataFrame]:
    try:
        df = pd.read_csv(csv_path)
    except (EmptyDataError, FileNotFoundError):
        return None

    if df.empty or "event_timestamp" not in df.columns or "event_name" not in df.columns:
        return None

    df = df[["event_timestamp", "event_name"]].copy()
    df["event_timestamp"] = pd.to_datetime(df["event_timestamp"], format="mixed", errors="coerce")
    df = df.dropna(subset=["event_timestamp"])
    if df.empty:
        return None

    return df


def load_glance_event_stream(
    idle_csv: str,
    shutdown_csv: str | None = None,
    gap_csv: str | None = None,
) -> Optional[pd.DataFrame]:
    frames = []

    idle_df = load_event_slice(idle_csv)
    if idle_df is not None:
        frames.append(idle_df)

    if shutdown_csv:
        shutdown_df = load_event_slice(shutdown_csv)
        if shutdown_df is not None:
            frames.append(shutdown_df)

    if gap_csv:
        gap_df = load_event_slice(gap_csv)
        if gap_df is not None:
            frames.append(gap_df)

    if not frames:
        return None

    events = pd.concat(frames, ignore_index=True)
    relevant_events = {GLANCE_START_EVENT, GLANCE_END_EVENT, UNLOCK_EVENT} | CANCEL_EVENTS
    events = events[events["event_name"].isin(relevant_events)]
    if events.empty:
        return None

    events = events.sort_values("event_timestamp", kind="mergesort").reset_index(drop=True)
    return events


def build_glance_blocks_from_events(events: pd.DataFrame) -> Optional[EventBlock]:
    if events is None or events.empty:
        return None

    head: Optional[EventBlock] = None
    prev: Optional[EventBlock] = None
    pending_start: Optional[pd.Timestamp] = None

    for _, row in events.iterrows():
        name = row["event_name"]
        ts = row["event_timestamp"]

        if name == GLANCE_START_EVENT:
            # Repeated wake events before resolution should use the latest wake time.
            pending_start = ts
        elif name == UNLOCK_EVENT:
            if pending_start is not None and ts >= pending_start:
                pending_start = None
        elif name == GLANCE_END_EVENT:
            if pending_start is not None and ts > pending_start:
                blk = EventBlock(block_type=EventBlock.TYPE_GLANCE, start_ts=pending_start, end_ts=ts)
                if head is None:
                    head = blk
                if prev is not None:
                    prev.next = blk
                prev = blk
            pending_start = None
        elif name in CANCEL_EVENTS:
            pending_start = None

    return head


def build_glance_blocks_from_csv(
    idle_csv: str,
    shutdown_csv: str | None = None,
    gap_csv: str | None = None,
) -> Optional[EventBlock]:
    events = load_glance_event_stream(idle_csv, shutdown_csv, gap_csv)
    return build_glance_blocks_from_events(events)
