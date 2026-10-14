"""Phone calls as their own state (pattern book addendum E5, David 10-13).

Tested on the Samsung test phone (10-13): a call is the time the call screen's foreground
service runs, from the first ring to the end. The ear sensor darkens the display without any
screen event, the side key closes the call screen while the call goes on, and a call answered
on the lock screen has no unlock - so neither the screen events nor the call screen alone
delimit a call; the service does.

  call            = service of a call app running (start -> stop), at least MIN_S long
  call time       = inside a call, the time the call app is the app in front (or no app is
                    in front because the display is dark): not screen time, not a glance
  use during call = other apps / home screen in front during a call: screen time as usual
  outcome         = 'declined' when the call screen closes within 1 s of the service stop
                    (it stays up 3-4 s after a missed or answered call); else 'ended'
                    (missed and answered cannot be told apart, only by length)
  device_started  = the call screen came up <= 1 s before a Screen Interactive (wake-up chain)

A1: the call services seen are com.samsung.android.incallui (34,575 starts), com.google.android
.dialer (19,220) and com.android.dialer (2,045). On Pixel-type phones the dialer and the in-call
screen are one package, so only its time inside a call is call time.
"""
import pandas as pd

from eyeslib.core.event_classes import canonical_name

CALL_PKGS = {"com.samsung.android.incallui", "com.google.android.dialer", "com.android.dialer"}
MIN_S = 2


def calls(df):
    """[{start, end, pkg, outcome, device_started}] (pandas Timestamps, UTC) from a log frame with
    app_package_name, interaction_type, event_timestamp."""
    names = {v: canonical_name(v) for v in df["interaction_type"].astype(str).unique()}
    it = df["interaction_type"].astype(str).map(names)
    t = pd.to_datetime(df["event_timestamp"], format="mixed", utc=True, errors="coerce")
    pk = df["app_package_name"].astype(str)
    d = pd.DataFrame({"t": t, "it": it, "pk": pk}).dropna(subset=["t"]).sort_values("t", kind="mergesort")
    out, open_ = [], {}
    for r in d.itertuples(index=False):
        if r.pk not in CALL_PKGS:
            continue
        if r.it == "Foreground Service Start" and r.pk not in open_:
            open_[r.pk] = r.t
        elif r.it == "Foreground Service Stop" and r.pk in open_:
            s = open_.pop(r.pk)
            if (r.t - s).total_seconds() >= MIN_S:
                out.append({"start": s, "end": r.t, "pkg": r.pk})
    one = pd.Timedelta(seconds=1)
    for c in out:
        w = d[(d.t >= c["start"] - one) & (d.t <= c["end"] + pd.Timedelta(seconds=6))]
        screen_on = w[w.it == "Screen Interactive"].t
        first_r = w[(w.pk == c["pkg"]) & (w.it == "Activity Resumed")].t
        c["device_started"] = bool(len(screen_on) and len(first_r) and
                                   abs((screen_on.iloc[0] - first_r.iloc[0]).total_seconds()) <= 1
                                   and screen_on.iloc[0] <= c["start"] + pd.Timedelta(seconds=3))
        after = w[(w.t >= c["end"]) & (w.pk == c["pkg"]) & (w.it == "Activity Paused")].t
        c["outcome"] = "declined" if len(after) and (after.iloc[0] - c["end"]).total_seconds() <= 1 else "ended"
        c["seconds"] = (c["end"] - c["start"]).total_seconds()
    return out


def call_time(rows, call_list):
    """Split app rows [(pkg, start, end)] (Timestamps) into (screen_rows, call_rows): the part of
    a call app's row inside a call is call time; everything else stays as it was."""
    screen, call = [], []
    for pkg, a, b in rows:
        if pkg not in CALL_PKGS:
            screen.append((pkg, a, b)); continue
        cur = a
        for c in sorted(call_list, key=lambda c: c["start"]):
            lo, hi = max(cur, c["start"]), min(b, c["end"] + pd.Timedelta(seconds=5))  # the 3-4 s "Call ended" screen
            if hi <= lo:
                continue
            if lo > cur:
                screen.append((pkg, cur, lo))
            call.append((pkg, lo, hi))
            cur = hi
        if cur < b:
            screen.append((pkg, cur, b))
    return screen, call
