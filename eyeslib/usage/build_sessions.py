"""
App-usage sessions (see the manual, "Sessions").

A session is a chain of apps in the foreground, one app on top at a time,
built only from app events. It does not depend on the screen state: a session
can happen while the device is IDLE (e.g. navigation shown on a car display).
Overlaying sessions with the device-state blocks is a separate step.

Foreground period of app A
    starts at A's Activity Resumed / Move to Foreground, and ends at the first of
      - A's Activity Paused / Move to Background             end_evidence = Paused
      - another app's Resumed while A is still on top          = next_resumed  (A's Paused missing)
      - A's Activity Stopped with no Paused before it, when A    = killed
        has not been Resumed in the previous 5 s (a Stopped soon
        after a Resumed of the same app belongs to the activity
        the app just left)
      - screen off, if A is not paused within 5 s of it        = screen_off
      - Device Shutdown / User Stopped                         = shutdown
      - a boot (Device Startup / User Unlocked) with no logged = power_off
        shutdown before it: the device was off. The boot burst is the
        run of events in the BOOT_BURST_SECONDS before the boot marker;
        the device was off in the gap just before the burst. The app on
        screen before that gap ends at its start, even if an app that
        came up with the boot has already replaced it (that app's link
        to it is cut). Apps that came up with the boot are not affected.
      - the end of the log                                     = end_of_log
    A Paused followed within 1 s by a Resumed of the same app is a switch
    between two activities of that app, not the end of the period.

Link A -> B
    B's period starts within LINK_SECONDS of A's period ending (and A did not
    end at screen off, shutdown or the end of the log). How the link was
    established is recorded:
      full            Paused(A) -> Resumed(B) -> Stopped(A)   (the full pattern)
      paused_resumed  Paused(A) -> Resumed(B), Stopped(A) not seen within 5 s
      resumed_only    Resumed(B) while A was on top (A's Paused missing)
      stopped_resumed A was stopped without a Paused, then Resumed(B)

Session
    a maximal chain of linked foreground periods.

Displays
    With Android Auto the phone drives two screens. An app that comes to the
    foreground while the phone is locked and Android Auto is connected is on
    the car display (eyeslib.usage.car_display). Each display has its own app
    on top: a car app ends at its own Paused, at the next app on the car, or
    when Android Auto disconnects (car_disconnected); apps on the phone do not
    end it, and screen off only affects the phone. Sessions are built per
    display, and car display time is reported separately, not as phone
    screen time.

Outputs (per reordered log)
    <stem>_SESSION.csv       one row per session
    <stem>_SESSION_APPS.csv  one row per app in each session's chain
"""
import os
import sys

import numpy as np
import pandas as pd

from eyeslib.segments.build_glance_blocks import is_system_package
from eyeslib.usage.car_display import AA_PACKAGE, FGS_STOP, display_state, displays

RESUME = {"Activity Resumed", "Move to Foreground"}
PAUSE = {"Activity Paused", "Move to Background"}
STOP = {"Activity Stopped", "Unknown importance: 23"}
SCREEN_OFF = {"Screen Non-interactive", "Unknown importance: 16"}
SHUTDOWN = {"Device Shutdown", "Unknown importance: 26", "User Stopped", "Unknown importance: 29"}
BOOT = {"Device Startup", "Unknown importance: 27", "User Unlocked", "Unknown importance: 28"}

LINK_SECONDS = 1.0          # handover gap: 98% of observed handovers are within 1 s
SAME_APP_SECONDS = 1.0      # Paused(A) -> Resumed(A) within this is an activity switch
SCREEN_OFF_GRACE = 5.0      # an app is normally paused within 1 s of screen off
STOP_WINDOW = 5.0           # Stopped(A) after Resumed(B) within this completes the pattern
BOOT_BURST_SECONDS = 60.0   # events this close before a boot marker belong to the boot: in A1 the boot
                            # marker follows the end of the preceding dark stretch within 60 s (manual)

NOT_LINKABLE_ENDS = {"screen_off", "shutdown", "power_off", "end_of_log", "car_disconnected", "moved_display"}


def load_events(reordered_csv):
    cols = ["app_package_name", "interaction_type", "event_timestamp", "application_label"]
    df = pd.read_csv(reordered_csv, usecols=lambda c: c in cols, low_memory=False)
    # times of all events of any kind: needed to find when an unlogged power-off happened
    df["t"] = pd.to_datetime(df["event_timestamp"], format="mixed", utc=True)
    df = df.dropna(subset=["t"]).sort_values("t", kind="mergesort")
    all_t = df["t"].values
    disp = display_state(df)              # keyguard + Android Auto timelines (car display)
    keep = RESUME | PAUSE | STOP | SCREEN_OFF | SHUTDOWN | BOOT
    aa_off = (df["app_package_name"] == AA_PACKAGE) & df["interaction_type"].isin(FGS_STOP)
    df = df[df["interaction_type"].isin(keep) | aa_off].reset_index(drop=True)
    kind = np.select(
        [df.interaction_type.isin(RESUME), df.interaction_type.isin(PAUSE), df.interaction_type.isin(STOP),
         df.interaction_type.isin(SCREEN_OFF), df.interaction_type.isin(BOOT),
         (df.app_package_name == AA_PACKAGE) & df.interaction_type.isin(FGS_STOP)],
        ["R", "P", "S", "OFF", "BOOT", "AAOFF"], "CUT")
    df["kind"] = kind
    if "application_label" not in df:
        df["application_label"] = ""
    df.attrs["all_t"] = all_t
    # the display of each Resumed: car if the phone is locked and Android Auto is connected
    is_r = (df["kind"] == "R").to_numpy()
    is_car = np.zeros(len(df), dtype=bool)
    if is_r.any():
        is_car[is_r] = displays(df.loc[is_r, "t"].values, disp) == "car"
    df.attrs["is_car"] = is_car
    return df


class Period:
    __slots__ = ("pkg", "label", "start", "end", "end_ev", "paused_at", "n_act", "link_ev", "last_resume", "display")

    def __init__(self, pkg, label, start, link_ev):
        self.pkg, self.label, self.start = pkg, label, start
        self.end = None
        self.end_ev = None
        self.paused_at = None
        self.n_act = 1
        self.link_ev = link_ev
        self.last_resume = start
        self.display = "phone"


class Screen:
    """State of one display: the app on top and decisions waiting on later events."""
    __slots__ = ("name", "top", "pending_off", "await_stop", "last_closed")

    def __init__(self, name):
        self.name, self.top, self.pending_off, self.await_stop, self.last_closed = name, None, None, None, None


def build_periods(df):
    """Walk the app events once and return foreground periods (each with its display)."""
    all_t = df.attrs.get("all_t")
    if all_t is None:
        all_t = df["t"].values
    is_car = df.attrs.get("is_car")
    if is_car is None:
        is_car = np.zeros(len(df), dtype=bool)
    periods = []
    phone, car = Screen("phone"), Screen("car")
    screens = (phone, car)
    last_cut = None              # time of the last logged shutdown

    def close(sc, t, ev):
        p = sc.top
        p.end, p.end_ev, p.display = t, ev, sc.name
        periods.append(p)
        sc.last_closed = p
        sc.top = None

    def screen_of(pkg):
        """The display whose top is this app (the most recently resumed if both), else the phone."""
        hits = [sc for sc in screens if sc.top is not None and sc.top.pkg == pkg]
        return max(hits, key=lambda sc: sc.top.last_resume) if hits else phone

    for i, (pkg, label, t, k) in enumerate(zip(df["app_package_name"].astype(str),
                                               df["application_label"].fillna("").astype(str), df["t"], df["kind"])):
        # resolve deferred decisions that this event's time settles
        for sc in screens:
            top = sc.top
            if top is not None and top.paused_at is not None \
                    and (t - top.paused_at).total_seconds() > SAME_APP_SECONDS:
                close(sc, top.paused_at, "Paused")
            if sc.top is not None and sc.pending_off is not None \
                    and (t - sc.pending_off).total_seconds() > SCREEN_OFF_GRACE:
                close(sc, sc.pending_off, "screen_off")
                sc.pending_off = None
            if sc.await_stop is not None and t > sc.await_stop[2]:
                sc.await_stop = None

        if k == "R":
            sc = car if is_car[i] else phone
            other = phone if sc is car else car
            if other.top is not None and other.top.pkg == pkg:
                # the app moved to the other display
                close(other, t, "moved_display")
                other.pending_off = None
            top = sc.top
            if top is not None:
                if pkg == top.pkg:
                    # another activity of the same app (with or without a Paused in between)
                    top.paused_at = None
                    top.n_act += 1
                    top.last_resume = t
                    sc.pending_off = None
                    continue
                if top.paused_at is not None:
                    close(sc, top.paused_at, "Paused")
                elif sc.pending_off is not None:
                    close(sc, sc.pending_off, "screen_off")
                else:
                    close(sc, t, "next_resumed")
                sc.pending_off = None
            link = None
            prev = sc.last_closed
            if prev is not None and prev.end_ev not in NOT_LINKABLE_ENDS \
                    and (t - prev.end).total_seconds() <= LINK_SECONDS:
                link = {"Paused": "paused_resumed", "next_resumed": "resumed_only",
                        "killed": "stopped_resumed"}[prev.end_ev]
            sc.top = Period(pkg, label, t, link)
            sc.top.display = sc.name
            sc.await_stop = (sc.top, prev.pkg, t + pd.Timedelta(seconds=STOP_WINDOW)) \
                if link == "paused_resumed" else None

        elif k == "P":
            sc = screen_of(pkg)
            top = sc.top
            if top is not None and pkg == top.pkg and top.paused_at is None:
                if sc.pending_off is not None:
                    close(sc, t, "Paused")       # paused shortly after screen off: normal
                    sc.pending_off = None
                else:
                    top.paused_at = t

        elif k == "S":
            for sc in screens:
                if sc.await_stop is not None and pkg == sc.await_stop[1]:
                    sc.await_stop[0].link_ev = "full"
                    sc.await_stop = None
            sc = screen_of(pkg)
            top = sc.top
            if top is not None and pkg == top.pkg:
                if top.paused_at is not None:
                    close(sc, top.paused_at, "Paused")
                    sc.pending_off = None
                elif (t - top.last_resume).total_seconds() > STOP_WINDOW:
                    close(sc, t, "killed")
                    sc.pending_off = None
                # else: the Stopped of the activity this app just switched away from

        elif k == "OFF":
            # the phone's screen went off; the car display is not affected
            top = phone.top
            if top is not None:
                if top.paused_at is not None:
                    close(phone, top.paused_at, "Paused")
                elif phone.pending_off is None:
                    phone.pending_off = t

        elif k == "AAOFF":
            # Android Auto disconnected: whatever was on the car display has left it
            top = car.top
            if top is not None:
                close(car, top.paused_at if top.paused_at is not None else t,
                      "Paused" if top.paused_at is not None else "car_disconnected")
            car.await_stop = None

        elif k == "BOOT":
            # A boot with no shutdown logged before it: the device was off in the gap just before the
            # boot burst. Whatever was on screen before that gap left the screen when the device went off.
            j = int(np.searchsorted(all_t, t.to_datetime64() - np.timedelta64(int(BOOT_BURST_SECONDS * 1e9), "ns"),
                                    "left"))
            if j == 0:
                continue
            gs, ge = pd.Timestamp(all_t[j - 1], tz="UTC"), pd.Timestamp(all_t[j], tz="UTC")
            if last_cut is not None and last_cut >= gs:
                continue                 # the shutdown was logged: already handled at the shutdown
            for sc in screens:
                top = sc.top
                if top is not None and top.start <= gs:
                    if top.paused_at is not None:
                        close(sc, top.paused_at, "Paused")
                    elif sc.pending_off is not None:
                        close(sc, sc.pending_off, "screen_off")
                    else:
                        close(sc, gs, "power_off")
                    sc.pending_off = None
                    sc.await_stop = None
                    continue
                # an app that came up with the boot has already replaced the one from before the gap
                for p in reversed(periods):
                    if p.display != sc.name:
                        continue
                    if p.end <= gs:
                        break
                    if p.start <= gs and p.end >= ge and p.end_ev == "next_resumed":
                        old_end = p.end
                        p.end, p.end_ev = gs, "power_off"
                        for q in periods + ([sc.top] if sc.top is not None else []):
                            if q.display == sc.name and q.start == old_end:
                                q.link_ev = None
                        break

        else:  # CUT: shutdown
            last_cut = t
            for sc in screens:
                top = sc.top
                if top is not None:
                    close(sc, top.paused_at if top.paused_at is not None else t,
                          "Paused" if top.paused_at is not None else "shutdown")
                sc.pending_off = None
                sc.await_stop = None

    for sc in screens:
        top = sc.top
        if top is not None:
            if top.paused_at is not None:
                close(sc, top.paused_at, "Paused")
            elif sc.pending_off is not None:
                close(sc, sc.pending_off, "screen_off")
            else:
                close(sc, df["t"].iloc[-1], "end_of_log")
    return periods


def build_sessions(periods):
    """Sessions per display, numbered together in order of start time."""
    s_parts, a_parts = [], []
    for disp in ("phone", "car"):
        s, a = build_sessions_one_display([p for p in periods if p.display == disp])
        if len(s):
            s["display"], a["display"] = disp, disp
            s["_k"], a["_k"] = disp + s["session_id"].astype(str), disp + a["session_id"].astype(str)
            s_parts.append(s)
            a_parts.append(a)
    if not s_parts:
        return pd.DataFrame(), pd.DataFrame()
    s = pd.concat(s_parts).sort_values(["start_time", "display"], kind="mergesort").reset_index(drop=True)
    new_id = dict(zip(s["_k"], range(1, len(s) + 1)))
    s["session_id"] = s["_k"].map(new_id)
    a = pd.concat(a_parts)
    a["session_id"] = a["_k"].map(new_id)
    a = a.sort_values(["session_id", "order"], kind="mergesort").reset_index(drop=True)
    return s.drop(columns="_k"), a.drop(columns="_k")


def build_sessions_one_display(periods):
    """Group linked periods into sessions; merge consecutive periods of the same app."""
    sessions, apps = [], []
    sid = 0
    chain = []

    def flush():
        nonlocal chain
        if not chain:
            return
        # merge consecutive same-app periods into one chain entry
        merged = []
        for p in chain:
            if merged and merged[-1]["pkg"] == p.pkg:
                m = merged[-1]
                m["end"], m["end_ev"], m["n_act"] = p.end, p.end_ev, m["n_act"] + p.n_act
            else:
                merged.append(dict(pkg=p.pkg, label=p.label, start=p.start, end=p.end, end_ev=p.end_ev,
                                   n_act=p.n_act, link=p.link_ev))
        for i, m in enumerate(merged, start=1):
            apps.append(dict(session_id=sid, order=i, app_package_name=m["pkg"], app_label=m["label"],
                             start_time=m["start"], end_time=m["end"],
                             duration_s=round((m["end"] - m["start"]).total_seconds(), 3),
                             n_activities=m["n_act"], end_evidence=m["end_ev"],
                             link_from_previous=m["link"] if i > 1 else "",
                             system_app=is_system_package(m["pkg"])))
        links = [m["link"] for m in merged[1:]]
        start, end = merged[0]["start"], merged[-1]["end"]
        sessions.append(dict(
            session_id=sid, start_time=start, end_time=end,
            duration_s=round((end - start).total_seconds(), 3),
            n_apps=len(merged), first_app=merged[0]["pkg"], last_app=merged[-1]["pkg"],
            chain=" > ".join(m["pkg"] for m in merged),
            end_evidence=merged[-1]["end_ev"],
            links_full=sum(l == "full" for l in links),
            links_inferred=sum(l != "full" for l in links),
            system_only=all(is_system_package(m["pkg"]) for m in merged)))
        chain = []

    for p in periods:
        if not chain or p.link_ev is None:
            flush()
            sid += 1
        chain.append(p)
    flush()
    return pd.DataFrame(sessions), pd.DataFrame(apps)


def process_file(reordered_csv, out_dir):
    df = load_events(reordered_csv)
    periods = build_periods(df) if len(df) else []
    s, a = build_sessions(periods)
    stem = os.path.basename(reordered_csv)[:-len(".csv")]
    os.makedirs(out_dir, exist_ok=True)
    s_cols = ["session_id", "start_time", "end_time", "duration_s", "n_apps", "first_app", "last_app", "chain",
              "end_evidence", "links_full", "links_inferred", "system_only", "display"]
    a_cols = ["session_id", "order", "app_package_name", "app_label", "start_time", "end_time", "duration_s",
              "n_activities", "end_evidence", "link_from_previous", "system_app", "display"]
    s.reindex(columns=s_cols).to_csv(os.path.join(out_dir, f"{stem}_SESSION.csv"), index=False)
    a.reindex(columns=a_cols).to_csv(os.path.join(out_dir, f"{stem}_SESSION_APPS.csv"), index=False)
    return s, a


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python -m eyeslib.usage.build_sessions <reordered.csv> <out_dir>")
        sys.exit(1)
    s, a = process_file(sys.argv[1], sys.argv[2])
    print(f"{len(s)} sessions, {len(a)} app entries -> {sys.argv[2]}")
