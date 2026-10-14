"""
GLANCE detection (see the manual, "Glance Logic").

Definition (Parry & Toth 2025, Computational Communication Research 7(1),
"Extracting Meaningful Measures of Smartphone Usage from Android Event Log
Data"): a glance is a screen activation that ends without the device being
unlocked. App activity inside it (answering a call, replying from a
notification, controlling audio) belongs to the glance and is not evidence
of use (David, 2026-10-12: match the CCR paper).

Wake session
    [t_s, t_e]: t_s is a Screen Interactive event, t_e is the first Screen
    Non-interactive event after it. A repeated Screen Interactive before t_e
    restarts the session. A SHUTDOWN boundary (Device Shutdown, User Stopped)
    or the start of a GAP before t_e makes the session incomplete; it is not
    classified. Events at the same instant as t_s or t_e belong to the session.

GLANCE
    a complete wake session with no Keyguard Hidden (unlock) inside [t_s, t_e].

Devices without a lock screen (exception, David 2026-10-12)
    A device that never or rarely logs an unlock cannot show "never unlocked",
    so CCR's rule would turn all its use into glances. If the file has fewer
    than NO_LOCK_RATIO Keyguard Hidden events per Screen Interactive event,
    it is treated as having no lock screen and gets no GLANCE blocks (every
    wake is a session). Such files are reported separately.

Android Auto (David 2026-10-13, car tests 1a-1f; eyeslib.states.car)
    While the phone projects to a car, no screen-off is logged, so the whole
    projection reads as one screen-on; at its end the screen comes on, locked,
    for 5-18 s. A wake session that overlaps a projection, or is that screen
    left on at its end, is car state and never a GLANCE.
"""
from typing import Optional

import pandas as pd
from pandas.errors import EmptyDataError

from eyeslib.core.event_block import EventBlock
from eyeslib.states import car


GLANCE_START_EVENT = "Screen Interactive"
GLANCE_END_EVENT = "Screen Non-interactive"
UNLOCK_EVENT = "Keyguard Hidden"
LOCK_EVENT = "Keyguard Shown"
CANCEL_EVENTS = {"Device Shutdown", "User Stopped", "Gap Start"}

APP_RESUMED = "App Resumed"
APP_PAUSED = "App Paused"
RESUME_TYPES = {"Activity Resumed", "Move to Foreground"}
PAUSE_TYPES = {"Activity Paused", "Move to Background"}

# Below this many Keyguard Hidden per Screen Interactive, the device is taken
# to have no lock screen (verification 2026-09-29, issue #2).
NO_LOCK_RATIO = 0.1

# System packages (lock screen, home screen); used by build_sessions.
SYSTEM_PACKAGES = {
    "android",
    "com.android.systemui",
    "org.chromium.arc.home",   # ChromeOS (ARC) home screen
    "com.amazon.kindle.kso",   # Fire lock screen ("special offers")
}


def is_system_package(pkg) -> bool:
    pkg = str(pkg)
    return "launcher" in pkg or pkg in SYSTEM_PACKAGES


def load_event_slice(csv_path: str) -> Optional[pd.DataFrame]:
    try:
        df = pd.read_csv(csv_path)
    except (EmptyDataError, FileNotFoundError):
        return None

    if df.empty or "event_timestamp" not in df.columns or "event_name" not in df.columns:
        return None

    df = df[["event_timestamp", "event_name"]].copy()
    df["app_package_name"] = None
    df["event_timestamp"] = pd.to_datetime(df["event_timestamp"], format="mixed", errors="coerce")
    df = df.dropna(subset=["event_timestamp"])
    if df.empty:
        return None

    return df


def load_app_events(activity_csv: str) -> Optional[pd.DataFrame]:
    """Foreground/background events of non-system apps from the reordered log."""
    try:
        df = pd.read_csv(activity_csv, usecols=["app_package_name", "interaction_type", "event_timestamp"])
    except (EmptyDataError, FileNotFoundError, ValueError):
        return None

    df = df[df["interaction_type"].isin(RESUME_TYPES | PAUSE_TYPES)]
    df = df[~df["app_package_name"].map(is_system_package)]
    if df.empty:
        return None

    df = df.assign(
        event_name=df["interaction_type"].map(lambda x: APP_RESUMED if x in RESUME_TYPES else APP_PAUSED),
        event_timestamp=pd.to_datetime(df["event_timestamp"], format="mixed", errors="coerce"),
    )[["event_timestamp", "event_name", "app_package_name"]]
    return df.dropna(subset=["event_timestamp"])


def load_glance_event_stream(
    idle_csv: str,
    shutdown_csv: str | None = None,
    gap_csv: str | None = None,
    activity_csv: str | None = None,
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

    if activity_csv:
        app_df = load_app_events(activity_csv)
        if app_df is not None:
            frames.append(app_df)

    if not frames:
        return None

    events = pd.concat(frames, ignore_index=True)
    relevant_events = {GLANCE_START_EVENT, GLANCE_END_EVENT, UNLOCK_EVENT, LOCK_EVENT, APP_RESUMED, APP_PAUSED} | CANCEL_EVENTS
    events = events[events["event_name"].isin(relevant_events)]
    if events.empty:
        return None

    # Order of events that share a timestamp: a wake session encloses every
    # event at its own start and end instant, so Screen Interactive goes first
    # and Screen Non-interactive goes last. If both occur at the same instant,
    # the screen went off and straight back on: the Non-interactive (closing the
    # previous session) goes before the Interactive (opening the next one).
    ts = events["event_timestamp"]
    si_at_same_instant = ts.isin(set(ts[events["event_name"] == GLANCE_START_EVENT]))
    rank = pd.Series(1, index=events.index)
    rank[events["event_name"] == GLANCE_START_EVENT] = 0
    rank[events["event_name"] == GLANCE_END_EVENT] = 2
    rank[(events["event_name"] == GLANCE_END_EVENT) & si_at_same_instant] = -1
    events = (events.assign(_rank=rank)
                    .sort_values(["event_timestamp", "_rank"], kind="mergesort")
                    .drop(columns="_rank")
                    .reset_index(drop=True))
    return events


def has_lock_screen(events: pd.DataFrame, ratio: float = NO_LOCK_RATIO) -> bool:
    """False when the file logs fewer than `ratio` unlocks per screen-on."""
    wakes = int((events["event_name"] == GLANCE_START_EVENT).sum())
    unlocks = int((events["event_name"] == UNLOCK_EVENT).sum())
    return wakes == 0 or unlocks >= ratio * wakes


def build_glance_blocks_from_events(events: pd.DataFrame, car_tracks: Optional[dict] = None) -> Optional[EventBlock]:
    if events is None or events.empty:
        return None
    # The lock screen counts only from the first unlock on (10-13: the Samsung test phone got
    # a lock that morning; its sessions of the days before were not glances).
    unlocks = events.loc[events["event_name"] == UNLOCK_EVENT, "event_timestamp"]
    if unlocks.empty:
        print("[INFO] no unlock logged: no lock screen, no GLANCE blocks")
        return None
    lock_since = unlocks.min()
    events = events[events["event_timestamp"] >= lock_since]
    if not has_lock_screen(events):
        print(f"[INFO] no lock screen (Keyguard Hidden / Screen Interactive < {NO_LOCK_RATIO}): no GLANCE blocks")
        return None

    head: Optional[EventBlock] = None
    prev: Optional[EventBlock] = None

    session_start: Optional[pd.Timestamp] = None  # t_s of the open wake session
    unlocked = False
    # Is the lock screen up? A screen that times out may come back on without a lock: no
    # Keyguard Shown at the screen-off (Samsung "lock after timeout" delay, Smart Lock).
    # Such a session starts unlocked and is not a glance (10-13, Samsung test phone).
    keyguard_up = True          # unknown at the start: as before, assume locked
    session_locked = True
    logs_lock = bool((events["event_name"] == LOCK_EVENT).any())   # without Keyguard Shown, never assume unlocked

    for name, ts in zip(events["event_name"], events["event_timestamp"]):
        if name == LOCK_EVENT:
            keyguard_up = True
            if session_start is not None:
                session_locked = True
            continue
        if name == UNLOCK_EVENT and logs_lock:
            keyguard_up = False
        if name == GLANCE_START_EVENT:
            # A repeated wake before the session ends restarts the session.
            session_start = ts
            unlocked = False
            session_locked = keyguard_up
        elif session_start is None:
            continue
        elif name in CANCEL_EVENTS:
            session_start = None  # incomplete session: not classified
        elif name == UNLOCK_EVENT:
            unlocked = True
        elif name == GLANCE_END_EVENT:
            in_car = car_tracks is not None and car.is_glance_free(
                pd.Timestamp(session_start).tz_localize("UTC") if pd.Timestamp(session_start).tzinfo is None else pd.Timestamp(session_start),
                pd.Timestamp(ts).tz_localize("UTC") if pd.Timestamp(ts).tzinfo is None else pd.Timestamp(ts), car_tracks)
            if session_locked and not unlocked and ts > session_start and not in_car:
                blk = EventBlock(block_type=EventBlock.TYPE_GLANCE, start_ts=session_start, end_ts=ts)
                if head is None:
                    head = blk
                if prev is not None:
                    prev.next = blk
                prev = blk
            session_start = None

    return head


def build_glance_blocks_from_csv(
    idle_csv: str,
    shutdown_csv: str | None = None,
    gap_csv: str | None = None,
    activity_csv: str | None = None,
) -> Optional[EventBlock]:
    events = load_glance_event_stream(idle_csv, shutdown_csv, gap_csv, activity_csv)
    tracks = None
    if activity_csv:
        try:
            log = pd.read_csv(activity_csv, usecols=lambda c: c in ("app_package_name", "app_class_name", "interaction_type", "event_timestamp"))
            tracks = car.tracks(log)
            if tracks["proj"]:
                print(f"[INFO] Android Auto: {len(tracks['proj'])} projections, no GLANCE inside or at their ends")
        except (EmptyDataError, FileNotFoundError, ValueError):
            tracks = None
    return build_glance_blocks_from_events(events, tracks)
