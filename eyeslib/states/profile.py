"""
Segment profile of a log (see the manual, "Segment profile").

A file is described by three independent tracks over the same timeline; the device state and the app usage are read
from how they overlap.

    track "silence"   every gap of at least TOLERANCE_SECONDS between two consecutive events. Nothing else assumed.
    track "key"       built from system events only:
                        off        a stretch closed by logged power events or the boot signature (kind detail = sign)
                        startup / user_unlocked / shutdown    the markers themselves (points)
                        storm      a boot storm: STORM_MIN_EVENTS or more Standby Bucket Changed with gaps of at most
                                   STORM_GAP_SECONDS
                        screen_on / screen_off / screen_unknown    between screen events; flag when the closing
                                   event was lost
                        unlocked / locked    Keyguard Hidden -> Keyguard Shown and back
                        heartbeat  a run of background events with no gap of TOLERANCE_SECONDS or more and no other
                                   event in between (the device is on)
    track "app"       built from app events only, two kinds:
                      in_front: Activity Resumed -> Paused (or Stopped) of the same app = the app is in front.
                      pip / pip_back / pip_wake: small-window periods, from the app's Paused to its next Stopped
                      or Resumed (see pip_track): still visible in a small window.
                      service / service_mark: an app's Foreground Service Start -> Stop (see service_track): the
                      device is On, the screen possibly off.
                      car / car_maps / car_incomplete: a special case, from the foreground-service events of two user
                      apps, Android Auto and Maps (see car_track): the map is on a car screen.
                      For in_front: flag: "no start" (a pause with no resume: logging was lost), "no pause" (closed by
                      the next app's resume, a power event or the end of the log).

First version: the tracks are written out and shown; the device-state rules still live in device_state.py.
"""
import re
import numpy as np
import pandas as pd

from . import device_state as ds

CAR_APP = "com.google.android.projection.gearhead"       # Android Auto
MAPS_APP = "com.google.android.apps.maps"
CAR_MIN_SECONDS = 300.0        # a car-screen session lasts at least 5 minutes (reviewer, 2026-10-02)
CAR_MAX_SECONDS = 12 * 3600.0  # a longer session is not a drive: review
CAR_END_SECONDS = 10.0         # trip end: Maps service stop, then Android Auto service stop within this
CAR_START_SECONDS = 300.0      # trip start: Android Auto service start, then Maps service start within this
CAR_RESTART_SECONDS = 60.0     # Android Auto's service restarts within seconds at connection: one session   (no longer used, 2026-10-07)
CAR_END_BEFORE = 1.0           # end mark: the Android Auto service stop comes from this long before a Maps service stop ...
CAR_END_AFTER = 2.0            # ... to this long after it (A1 distribution, 2026-10-07)
CAR_START_MARK = 5.0           # start mark: Maps Resumed within this after the Android Auto service start (A1: most within 3 s)
STORM_MIN_EVENTS = 20
STORM_GAP_SECONDS = 2.0
COLS = ["track", "kind", "start", "end", "duration_s", "app", "flag", "n", "grade"]
# grade (reviewer, 2026-10-03): every track is built on its own and marks each segment "confirmed", "likely" or
# "unknown"; "" = not graded yet. Tracks are fused afterwards; only a confirmed segment of another track may upgrade.


def _rows(track, kind, start, end, app="", flag="", n=1, grade=""):
    start, end = np.asarray(start, dtype=float), np.asarray(end, dtype=float)
    return pd.DataFrame(dict(track=track, kind=kind, start=start, end=end, duration_s=end - start, app=app, flag=flag, n=n, grade=grade))


def silence_track(t):
    d = np.diff(t)
    k = np.where(d >= ds.TOLERANCE_SECONDS)[0]
    return _rows("silence", "silence", t[k], t[k + 1])


def key_track(ev, x):
    t, nm, cls = ev["t"].to_numpy(), ev["name"].to_numpy(), ev["cls"].to_numpy()
    n = len(t)
    out = []
    # power: Off stretches decided by logged events or the boot signature, and the markers
    rn = np.array(ds.RULES + [""], dtype=object)
    k = np.where(np.isin(x["off_sign"], [ds._R[r] for r in ds.POWER_OFF_SIGNS]))[0]
    out.append(_rows("key", "off", t[k], t[k + 1], flag=rn[x["off_sign"][k]]))
    for name, kind in [("Device Shutdown", "shutdown"), ("Device Startup", "startup"), ("User Unlocked", "user_unlocked")]:
        i = np.where(nm == name)[0]
        out.append(_rows("key", kind, t[i], t[i]))
    # boot storms
    sb = np.where(nm == "Standby Bucket Changed")[0]
    if len(sb):
        cut = np.where(np.diff(t[sb]) > STORM_GAP_SECONDS)[0] + 1
        a, b = np.r_[0, cut], np.r_[cut, len(sb)]
        big = (b - a) >= STORM_MIN_EVENTS
        out.append(_rows("key", "storm", t[sb[a[big]]], t[sb[b[big] - 1]], n=(b - a)[big]))
    # screen
    for s, e, state, end in ds.screen_runs(nm):
        e = min(e, n - 1)
        if e <= s:
            continue
        lost = ("screen-off lost" if end != "off" else "") if state == "on" else \
               ("screen-on lost" if end == "off" else "") if state == "off" else ""
        out.append(_rows("key", "screen_" + (state if state in ("on", "off") else "unknown"), [t[s]], [t[e]], flag=lost))
    # lock
    kg = np.where(np.isin(nm, ["Keyguard Hidden", "Keyguard Shown"]))[0]
    if len(kg) > 1:
        hid = nm[kg] == "Keyguard Hidden"
        chg = np.r_[True, hid[1:] != hid[:-1]]                # first event of each run of the same kind
        st = kg[chg]
        kinds = np.where(hid[chg], "unlocked", "locked")
        out.append(_rows("key", kinds[:-1], t[st[:-1]], t[st[1:]]))
    # heartbeat stretches
    hb = cls == "heartbeat"
    if hb.any():
        brk = np.r_[True, (np.diff(t) >= ds.TOLERANCE_SECONDS) | ~hb[1:] | ~hb[:-1]]
        run = np.cumsum(brk)
        g = pd.DataFrame(dict(run=run[hb], t=t[hb])).groupby("run")["t"].agg(["min", "max", "size"])
        g = g[g["size"] >= 2]
        out.append(_rows("key", "heartbeat", g["min"].to_numpy(), g["max"].to_numpy(), n=g["size"].to_numpy()))
    return pd.concat(out, ignore_index=True)


def car_track(ev):
    """Car projection periods (Android Auto), rebuilt 2026-10-07 from tests on a phone in a car (six sessions) and
    the reviewer's rule: a projection that really ends has ended, whatever the cause; a reconnection seconds later
    is a new projection. No merging across a gap and no minimum length.
    What the phone logs (class names are lost in Chronicle, so everything is by package):
      end    Android Auto's foreground service stops together with the Maps service (unplugging: Maps navigation
             service stop, Maps Stopped and the Android Auto stop within a second). END MARK = an Android Auto
             service stop within CAR_END_BEFORE .. CAR_END_AFTER seconds of a Maps service stop (A1: of 7,115 Maps
             service stops, 3,862 have the Android Auto stop from 0.5 s before to 2 s after; almost none 2-5 s).
      start  Android Auto runs short set-up services first and its projection service last (a burst of service
             starts and stops within a second or two), flashes one of its own screens over the app in front, then
             the map appears on the car screen. START MARK = a burst of Android Auto service events with a Maps
             Resumed or Maps service start within CAR_START_MARK seconds after it, or with an Android Auto screen
             Resumed inside it. START = the first service start of that burst.
    The earlier version merged restarts within 60 s and so ran on for an hour of ordinary phone use after the real
    end (Android Auto restarts a waiting service 3 s after a disconnect).
    Rows:
      car             start -> end mark. grade confirmed = start mark too; likely = start not marked (flag says so).
                      n = Maps service runs inside.
      car_maps        each Maps service run inside (start -> next stop). While projecting, this service means "Maps
                      is on the car screen", not that a route is followed.
      car_incomplete  grade unknown, for review: a start mark with no end mark before the next start (ends at the
                      next Android Auto service stop), or a period with a power event, a silence of
                      LONG_QUIET_OFF_SECONDS or more, or longer than CAR_MAX_SECONDS inside."""
    t, nm = ev["t"].to_numpy(), ev["name"].to_numpy()
    pkg = ev["app_package_name"].astype(str).to_numpy()
    fs, fe = nm == "Foreground Service Start", nm == "Foreground Service Stop"
    gs, ge = t[(pkg == CAR_APP) & fs], t[(pkg == CAR_APP) & fe]
    ms, me = t[(pkg == MAPS_APP) & fs], t[(pkg == MAPS_APP) & fe]
    mr = t[(pkg == MAPS_APP) & (nm == "Activity Resumed")]
    if not len(ge) or not len(gs) or not len(me):
        return pd.DataFrame(columns=COLS)
    pw = t[np.isin(nm, ["Device Shutdown", "Device Startup"])]
    gaps = np.diff(t)

    def between(ref, lo, hi):
        return np.searchsorted(ref, hi, "right") - np.searchsorted(ref, lo, "left")

    # Android Auto's service events come in bursts (set-up services handing over within a second, at connection and
    # again at disconnection). Read each burst as a whole.
    ga = np.sort(np.r_[gs, ge])
    cut = np.where(np.diff(ga) > CAR_END_AFTER)[0] + 1
    b_lo, b_hi = ga[np.r_[0, cut]], ga[np.r_[cut - 1, len(ga) - 1]]
    ar = t[(pkg == CAR_APP) & (nm == "Activity Resumed")]
    car, maps, inc, open_, prev_end, last_burst = [], [], [], None, -1e18, None
    open_last = last_last = -1e18

    def finish(a, e, marked):
        # The projection itself begins when the map appears on the car screen: the first Maps Resumed or Maps service
        # start after the connection burst. Between plugging in and that moment the phone is still an ordinary phone
        # (A1: 531 of the 621 screen-offs found inside connection-to-end periods fall before it).
        k1, k2 = np.searchsorted(mr, a, "left"), np.searchsorted(ms, a, "left")
        m0 = min(mr[k1] if k1 < len(mr) else np.inf, ms[k2] if k2 < len(ms) else np.inf)
        if m0 < e:
            a = m0
        else:
            marked = False
        i0, i1 = np.searchsorted(t, a, "left"), np.searchsorted(t, e, "right")
        quiet = i1 - 1 > i0 and gaps[i0:i1 - 1].max() >= ds.LONG_QUIET_OFF_SECONDS
        bad = "a silence of 6 h or more inside" if quiet else "longer than 12 h" if e - a >= CAR_MAX_SECONDS else \
              "a shutdown or boot inside" if between(pw, a, e) > 0 else ""
        if bad:
            inc.append((a, e, bad))
            return
        runs = []
        for s0 in ms[(ms >= a - 5) & (ms <= e)]:
            jj = np.searchsorted(me, s0, "right")
            if jj < len(me) and me[jj] <= e + CAR_END_AFTER and (not runs or s0 >= runs[-1][1]):
                runs.append((s0, me[jj]))
        car.append((a, e, len(runs), "" if marked else "start not marked", "confirmed" if marked else "likely"))
        maps.extend(runs)

    for lo, hi in zip(b_lo, b_hi):
        st = ge[(ge >= lo) & (ge <= hi)]
        j = np.searchsorted(me, st - CAR_END_AFTER, "left")
        beside = (j < len(me)) & (me[np.minimum(j, len(me) - 1)] <= st + CAR_END_BEFORE) if len(st) else np.zeros(0, bool)
        end_t = st[beside][0] if beside.any() else None                      # END MARK: the first stop beside a Maps service stop
        if end_t is not None:
            if open_ is not None and end_t > open_:
                finish(open_, end_t, True)
            elif open_ is None and last_burst is not None and last_burst > prev_end and end_t > last_burst:
                finish(last_burst, end_t, False)                             # no start mark: from the previous burst
            open_, prev_end = None, end_t
        sb = gs[(gs >= lo) & (gs <= hi)]
        sb = sb[sb > end_t] if end_t is not None else sb                     # a reconnection inside the same burst
        if len(sb):
            a0 = sb[0]
            mark = between(mr, a0, sb[-1] + CAR_START_MARK) > 0 or between(ms, a0, sb[-1] + CAR_START_MARK) > 0 or \
                (end_t is None and between(ar, lo - HANDOVER_SECONDS, hi + HANDOVER_SECONDS) > 0)
            if mark:                                                         # START MARK
                if open_ is not None and a0 - open_last <= CAR_START_MARK:
                    pass                                                     # still the same connection (set-up, then projection)
                else:
                    if open_ is not None and a0 > open_:
                        inc.append((open_, lo, "end not marked"))            # the earlier one never got its end
                    open_ = a0
                open_last = sb[-1]
            elif open_ is not None and a0 - open_last <= CAR_START_MARK:
                open_last = sb[-1]
            if last_burst is None or a0 - last_last > CAR_START_MARK:
                last_burst = a0
            last_last = sb[-1]
    if open_ is not None:
        inc.append((open_, min(t[-1], open_ + CAR_MAX_SECONDS), "end not marked"))
    out = []
    if car:
        c = np.array([x[:3] for x in car], dtype=float)
        out.append(_rows("app", "car", c[:, 0], c[:, 1], app=CAR_APP, n=c[:, 2].astype(int),
                         flag=[x[3] for x in car], grade=[x[4] for x in car]))
    if maps:
        m = np.array(maps, dtype=float)
        out.append(_rows("app", "car_maps", m[:, 0], m[:, 1], app=MAPS_APP, grade="confirmed"))
    if inc:
        inc = sorted(set(inc))
        out.append(_rows("app", "car_incomplete", [x[0] for x in inc], [x[1] for x in inc], app=CAR_APP,
                         flag=[x[2] for x in inc], grade="unknown"))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=COLS)


SERVICE_MIN_SECONDS = 60.0          # shorter service runs are blips (a sync, a notification): dropped
SERVICE_REVIEW_SILENCE = 1800.0     # a silence this long inside a run: did the service really run through it?


def service_track(ev, x, car=None):
    """Foreground-service segments of user apps: an app's Foreground Service Start directly followed by its own Stop,
    at least SERVICE_MIN_SECONDS long. Inside a service segment the device is On; the screen may be off (music).
    flag grades the segment by what lies inside it:
      clean    no silence of SERVICE_REVIEW_SILENCE or more: the device was On for the whole run
      review   a silence of SERVICE_REVIEW_SILENCE up to LONG_QUIET_OFF_SECONDS inside: the service ran through it
               (music playing), or its stop was lost
      broken   a logged shutdown / boot or a silence of LONG_QUIET_OFF_SECONDS or more inside: the stop was lost;
               not evidence
    n = 1 when the segment lies inside a confirmed car-screen session (the app may be on the car's screen or
    speakers), else 0. Unpaired events are kept as points: kind service_mark, flag "start with no stop" /
    "stop with no start"."""
    t, nm = ev["t"].to_numpy(), ev["name"].to_numpy()
    pkg = ev["app_package_name"].astype(str)
    user = ~(pkg.str.contains(ds.NON_USER_APP) | pkg.str.contains(ds.LOCKSCREEN_FEED_APP)).to_numpy()
    pkg = pkg.to_numpy()
    m = user & np.isin(nm, ["Foreground Service Start", "Foreground Service Stop"])
    if not m.any():
        return pd.DataFrame(columns=COLS)
    d = x["d"]
    off_t = t[:-1][np.isin(x["off_sign"], [ds._R[r] for r in ds.POWER_OFF_SIGNS])]
    big_t = t[:-1][d >= ds.LONG_QUIET_OFF_SECONDS]
    mid_t = t[:-1][(d >= SERVICE_REVIEW_SILENCE) & (d < ds.LONG_QUIET_OFF_SECONDS)]
    cars = car[car["kind"] == "car"][["start", "end"]].to_numpy() if car is not None and len(car) else np.zeros((0, 2))
    df = pd.DataFrame(dict(app=pkg[m], t=t[m], stop=nm[m] == "Foreground Service Stop"))
    out, marks = [], []
    for app, g in df.groupby("app", sort=False):
        k, tt = g["stop"].to_numpy(), g["t"].to_numpy()
        pair = np.where(~k[:-1] & k[1:])[0]
        a, b = tt[pair], tt[pair + 1]
        lone_s = np.setdiff1d(np.where(~k)[0], pair)
        lone_e = np.setdiff1d(np.where(k)[0], pair + 1)
        marks += [(tt[i], app, "start with no stop") for i in lone_s] + [(tt[i], app, "stop with no start") for i in lone_e]
        keep = (b - a) >= SERVICE_MIN_SECONDS
        a, b = a[keep], b[keep]
        if not len(a):
            continue
        has = lambda arr: (np.searchsorted(arr, b, "left") - np.searchsorted(arr, a, "left")) > 0
        flag = np.where(has(off_t) | has(big_t), "broken", np.where(has(mid_t), "review", "clean"))
        incar = np.zeros(len(a), dtype=int)
        if len(cars):
            j = np.maximum(np.searchsorted(cars[:, 0], a + 5, "right") - 1, 0)
            incar = ((a >= cars[j, 0] - 5) & (b <= cars[j, 1] + 5)).astype(int)
        out.append(_rows("app", "service", a, b, app=app, flag=flag, n=incar))
    if marks:
        mk = pd.DataFrame(marks, columns=["t", "app", "flag"])
        out.append(_rows("app", "service_mark", mk["t"].to_numpy(), mk["t"].to_numpy(), app=mk["app"].to_numpy(), flag=mk["flag"].to_numpy()))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=COLS)


PIP_MIN_SECONDS = 10.0              # fallback minimum, used when a file has too few ordinary pairs to measure its own
# Apps that can show a small window (reviewer, 2026-10-07: PiP exists only for a set of apps, mostly video). Read from
# A1: the share of an app's periods lasting a minute or more is 1-40% for these and under 0.5% for every other app
# (Chrome 0.09%, Gmail 0.07%, Messages 0.07%, Facebook 0.10%). Video, navigation and call apps.
PIP_APP = re.compile(
    r"^(?:com\.google\.android\.youtube|com\.netflix\.mediaclient|com\.google\.android\.apps\.maps|com\.disney\.disneyplus"
    r"|com\.hulu\.plus|com\.wbd\.stream|com\.peacocktv\.peacockandroid|com\.cbs\.app|com\.tubitv|com\.collegehumor\.chdropout"
    r"|com\.amazon\.avod\.thirdpartyclient|com\.google\.android\.apps\.tachyon|us\.zoom\.videomeetings|com\.microsoft\.teams"
    r"|com\.whatsapp|com\.facebook\.orca)$")
PIP_BASE_MIN_PAIRS = 200            # ordinary Paused -> Stopped pairs a file needs before its own limits are used


def stop_delay_limits(ev):
    """How late an ordinary Stopped arrives in THIS file (reviewer, 2026-10-07: files differ in difficulty, so no
    hard-coded minimum). Taken from apps that cannot have a small window (not PIP_APP): the delay from a Paused to
    the app's own Stopped, with another app Resumed in between and no screen-off at the pause. Returns
    (p99, p99.9, number of pairs); (PIP_MIN_SECONDS, PIP_MIN_SECONDS, n) when there are too few pairs.
    A1: p99 runs from 0.9 s to 31 s across files (median 4.1 s); p99.9 from 3.8 s to 549 s (median 18.6 s)."""
    t, nm = ev["t"].to_numpy(), ev["name"].to_numpy()
    pkg = ev["app_package_name"].astype(str)
    keep = ~(pkg.str.contains(ds.NON_USER_APP) | pkg.str.contains(ds.LOCKSCREEN_FEED_APP) | pkg.str.contains(PIP_APP)).to_numpy()
    pkg = pkg.to_numpy()
    res_t = t[nm == "Activity Resumed"]
    off_t = t[nm == "Screen Non-interactive"]
    m = keep & np.isin(nm, ["Activity Paused", "Activity Stopped", "Activity Resumed"])
    df = pd.DataFrame(dict(app=pkg[m], t=t[m], k=nm[m]))
    d = []
    for _, g in df.groupby("app", sort=False):
        k, tt = g["k"].to_numpy(), g["t"].to_numpy()
        i = np.where((k[:-1] == "Activity Paused") & (k[1:] == "Activity Stopped"))[0]
        if not len(i):
            continue
        a, b = tt[i], tt[i + 1]
        other = (np.searchsorted(res_t, b, "left") - np.searchsorted(res_t, a, "left")) > 0   # the app's own Resumed cannot lie between
        if len(off_t):
            j = np.searchsorted(off_t, a - 2, "left")
            other &= ~((j < len(off_t)) & (off_t[np.minimum(j, len(off_t) - 1)] <= a + 2))
        d.append((b - a)[other & ((b - a) < ds.LONG_QUIET_OFF_SECONDS)])
    d = np.concatenate(d) if d else np.zeros(0)
    if len(d) < PIP_BASE_MIN_PAIRS:
        return PIP_MIN_SECONDS, PIP_MIN_SECONDS, len(d)
    return float(np.quantile(d, 0.99)), float(np.quantile(d, 0.999)), len(d)


# System panels that open OVER an app and leave it visible: share sheet, print, photo / file picker, sign-in and
# permission prompts, screenshot tool, call screen, system dialogs. An app under one is Paused without being
# Stopped, the same log signature as a small window, but it is covered, not shrunk (test phone, Chrome, 2026-10-03:
# share sheet 10 s and print 15 s gave Paused -> Resumed with no Stopped). Listed by name from what was in front of
# such periods in A1. Home screens and user apps are NOT panels: with those in front the app is in a small window.
PANEL_APP = re.compile(
    r"(?:^android$|systemui|permissioncontroller|packageinstaller|intentresolver|photopicker|printspooler"
    r"|providers\.media|documentsui|smartcapture|credentialmanager|autofill|incallui|server\.telecom"
    r"|^com\.google\.android\.gms|^com\.google\.android\.tts$)")


def _last_before(ref, x):
    """For each x, the latest value of the sorted array ref that is <= x (-1e18 when there is none)."""
    if not len(ref):
        return np.full(len(x), -1e18)
    j = np.searchsorted(ref, x, "right") - 1
    return np.where(j >= 0, ref[np.maximum(j, 0)], -1e18)


def wake_pauses(ev):
    """The Paused that marks a small window coming back when the screen is turned on again (reviewer, 2026-10-03).
    Sequence rule, no time threshold. For one user app, with no other event of that app in between:
      Paused (the small window opens) -> screen-off -> Stopped, logged while the screen is off -> screen-on ->
      Paused (the small window is back; on a locked device it is logged at the unlock).
    The second Paused has no Resumed before it: it is not the end of a period in front, it is the START of a
    small-window period. Verified on a test phone (Galaxy S24+, Android 16; YouTube, 2026-10-03 08:39 and 08:55).
    Returns {app: array of the times of such Pauses}."""
    t, nm = ev["t"].to_numpy(), ev["name"].to_numpy()
    pkg = ev["app_package_name"].astype(str)
    user = ~(pkg.str.contains(ds.NON_USER_APP) | pkg.str.contains(ds.LOCKSCREEN_FEED_APP)).to_numpy()
    pkg = pkg.to_numpy()
    off_t, on_t = t[nm == "Screen Non-interactive"], t[nm == "Screen Interactive"]
    out = {}
    if not len(off_t) or not len(on_t):
        return out
    m = user & np.isin(nm, ["Activity Resumed", "Activity Paused", "Activity Stopped"])
    df = pd.DataFrame(dict(app=pkg[m], t=t[m], k=nm[m]))
    for app, g in df.groupby("app", sort=False):
        k, tt = g["k"].to_numpy(), g["t"].to_numpy()
        P, S = k == "Activity Paused", k == "Activity Stopped"
        i = np.where(P[2:] & S[1:-1] & P[:-2])[0] + 2
        if not len(i):
            continue
        p1, s_, p2 = tt[i - 2], tt[i - 1], tt[i]
        off = _last_before(off_t, s_)
        ok = (off > _last_before(on_t, s_)) & (off > p1) & (_last_before(on_t, p2) > s_)
        if ok.any():
            out[app] = p2[ok]
    return out


def pip_track(ev, car=None):
    """Picture-in-picture (small window) segments of user apps, counted separately from time in front. A segment
    starts at the app's Paused and ends at its next Stopped or Resumed (no other event of the app in between):
      pip       Paused -> Stopped: the small window was closed, or the screen went off
      pip_back  Paused -> Resumed: the small window was expanded back to full screen (reviewer's pattern, 2026-10-02)
      pip_wake  the Paused is the one that brings the window back at screen-on (wake_pauses) -> Stopped or Resumed
      cover     same pairing, but only system panels (PANEL_APP) came to the front in between: the app is covered by
                a share sheet, print screen, picker or prompt, not shrunk. Kept in this track as its own kind
                (reviewer, 2026-10-03); whether it goes back into the app's own screen time is decided at fusion
    Only apps in PIP_APP can have a small window; the same pattern for any other app is kind "visible" (still on
    screen for a cause we cannot name: a slow Stopped, split screen, a pop-up view), grade unknown, 10 s or more.
    Minimum length (reviewer, 2026-10-07): each file's own slow-Stopped limit, stop_delay_limits(): periods of the
    file's 99% delay or more are kept; those under its 99.9% delay are graded likely and flagged for review
    ("near the file's Stopped delay"), since about 1 in 100 ordinary Stoppeds is that late.
    For pip and pip_back: that minimum, at least one other app (the home screen counts) Resumed in
    between, not a pause caused by the screen going off (Screen Non-interactive within 2 s), no screen-off between
    for pip_back, and under LONG_QUIET_OFF_SECONDS. pip_wake needs none of these except the length cap: the Paused
    is identified by its sequence. Normally a Stopped follows a Paused within a second (88% of pairs in A1).
    Verified on a test phone (Galaxy S24+, Android 16; YouTube normal videos and Shorts). flag = the first other
    app that took the front (may be empty for pip_wake); n = 1 inside a confirmed car session."""
    t, nm = ev["t"].to_numpy(), ev["name"].to_numpy()
    pkg = ev["app_package_name"].astype(str)
    user = ~(pkg.str.contains(ds.NON_USER_APP) | pkg.str.contains(ds.LOCKSCREEN_FEED_APP)).to_numpy()
    pkg = pkg.to_numpy()
    res = nm == "Activity Resumed"
    res_t, res_p = t[res], pkg[res]
    off_t = t[nm == "Screen Non-interactive"]
    wake = wake_pauses(ev)
    lim99, lim999, _ = stop_delay_limits(ev)
    cut_t = np.sort(t[np.isin(nm, ["Screen Non-interactive", "Device Shutdown", "Device Startup"])])
    gaps = np.diff(t)
    cars = car[car["kind"] == "car"][["start", "end"]].to_numpy() if car is not None and len(car) else np.zeros((0, 2))
    m = user & np.isin(nm, ["Activity Resumed", "Activity Paused", "Activity Stopped"])
    df = pd.DataFrame(dict(app=pkg[m], t=t[m], k=nm[m]))
    out = []
    for app, g in df.groupby("app", sort=False):
        k, tt = g["k"].to_numpy(), g["t"].to_numpy()
        i = np.where((k[:-1] == "Activity Paused") & np.isin(k[1:], ["Activity Stopped", "Activity Resumed"]))[0]
        if not len(i):
            continue
        a, b, back = tt[i], tt[i + 1], k[i + 1] == "Activity Resumed"
        w = np.isin(a, wake.get(app, np.zeros(0)))
        lo, hi = np.searchsorted(res_t, a, "left"), np.searchsorted(res_t, b, "left")
        front = np.array([next((p for p in res_p[l:h] if p != app), "") for l, h in zip(lo, hi)], dtype=object)
        # covered by a panel: every other app that came to the front in between is a system panel
        panel = np.array([bool(h > l) and all(PANEL_APP.search(p) is not None for p in res_p[l:h] if p != app)
                          and any(p != app for p in res_p[l:h]) for l, h in zip(lo, hi)])
        if len(off_t):
            j = np.searchsorted(off_t, a - 2, "left")
            by_screen = (j < len(off_t)) & (off_t[np.minimum(j, len(off_t) - 1)] <= a + 2)
            off_between = np.searchsorted(off_t, b, "left") > np.searchsorted(off_t, a, "right")
        else:
            by_screen = off_between = np.zeros(len(a), bool)
        can_pip = PIP_APP.search(app) is not None
        plain = ((b - a) >= (lim99 if can_pip else PIP_MIN_SECONDS)) & (front != "") & ~by_screen & ~(back & off_between)
        ok = (w | plain) & ((b - a) < ds.LONG_QUIET_OFF_SECONDS)
        a, b, front, back, w, panel = a[ok], b[ok], front[ok], back[ok], w[ok], panel[ok]
        if not len(a):
            continue
        incar = np.zeros(len(a), dtype=int)
        if len(cars):
            c = np.maximum(np.searchsorted(cars[:, 0], a + 5, "right") - 1, 0)
            incar = ((a >= cars[c, 0] - 5) & (b <= cars[c, 1] + 5)).astype(int)
        kind = np.where(w, "pip_wake", np.where(panel, "cover", np.where(back, "pip_back", "pip")))
        if not can_pip:
            kind = np.where(kind == "cover", "cover", "visible")
        near = can_pip & ~w & ((b - a) < lim999)                             # inside the file's slow-Stopped tail
        # grade (reviewer, 2026-10-03). A screen-off always ends a small window (test phone), so a screen-off or a
        # power event INSIDE means the Stopped was lost: cut the segment there and keep the first part as likely.
        # Otherwise confirmed, or likely when a silence of ds.TOLERANCE_SECONDS (5 min) or more lies inside.
        ci = np.searchsorted(cut_t, a + 2, "right")
        has_cut = (ci < len(cut_t)) & (cut_t[np.minimum(ci, max(len(cut_t) - 1, 0))] < b - 2) if len(cut_t) else np.zeros(len(a), bool)
        b = np.where(has_cut, cut_t[np.minimum(ci, max(len(cut_t) - 1, 0))] if len(cut_t) else b, b)
        i0, i1 = np.searchsorted(t, a, "left"), np.searchsorted(t, b, "right")
        quiet = np.array([(gaps[x:y - 1].max() if y - 1 > x else 0.0) >= ds.TOLERANCE_SECONDS for x, y in zip(i0, i1)])
        grade = np.where(has_cut | quiet | near, "likely", "confirmed")
        grade = np.where(kind == "visible", "unknown", grade)
        flag = np.where(has_cut, "cut at screen-off", np.where(near, "near the file's Stopped delay", front))
        out.append(_rows("app", kind, a, b, app=app, flag=flag, n=incar, grade=grade))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=COLS)


HANDOVER_SECONDS = 1.0         # a pause may be logged up to this long after the next app's resume


def app_track(ev):
    """Apps in front, user apps only. A segment runs from an app's Activity Resumed to its Activity Paused.
    All apps take part in the pairing (a home screen coming to the front does end a user app), but only segments of
    user apps are returned (not system parts, home screens, lock-screen feeds: ds.NON_USER_APP, LOCKSCREEN_FEED_APP).
    flag:
      ""          both ends logged
      "no pause"  the end was not logged: closed by the next app's resume (when the app's own pause does not follow
                  within HANDOVER_SECONDS), by a power event, or by the end of the log
      "no start"  a pause with no resume before it (start = end = the pause): the start was lost. Not counted: the
                  Paused of a small window coming back at screen-on (wake_pauses); that one belongs to pip_track"""
    t, nm = ev["t"].to_numpy(), ev["name"].to_numpy()
    pkg = ev["app_package_name"].astype(str).to_numpy()
    idx = np.where(np.isin(nm, ["Activity Resumed", "Activity Paused", "Activity Stopped", "Device Shutdown", "Device Startup"]))[0]
    wake = {a: set(v.tolist()) for a, v in wake_pauses(ev).items()}
    rows, open_, pending = [], {}, {}                      # app -> start; app -> time at which another app took over

    def close(app, end, flag):
        pending.pop(app, None)
        rows.append((open_.pop(app), end, app, flag))
    for i in idx:
        name, p, ti = nm[i], pkg[i], t[i]
        for other in [a for a, tk in pending.items() if ti - tk > HANDOVER_SECONDS]:
            close(other, pending[other], "no pause")       # its pause never came
        if name == "Activity Resumed":
            for other in open_:
                if other != p:
                    pending.setdefault(other, ti)          # one app in front: wait briefly for the other's pause
            pending.pop(p, None)
            open_.setdefault(p, ti)
        elif name == "Activity Paused":
            if p in open_:
                close(p, ti, "")
            elif ti not in wake.get(p, ()):                # a small window back at screen-on is not a lost start
                rows.append((ti, ti, p, "no start"))
        elif name == "Activity Stopped":
            # a Stopped usually belongs to the app's PREVIOUS screen (Paused X, Resumed X, Stopped X when X moves
            # between its own screens), so it ends the segment only when another app has already taken over
            if p in open_ and p in pending:
                close(p, pending[p], "no pause")
        else:                                              # power event: nothing stays in front
            for other in list(open_):
                close(other, pending.get(other, ti), "no pause")
    for other in list(open_):
        close(other, pending.get(other, t[-1]), "no pause")
    if not rows:
        return pd.DataFrame(columns=COLS)
    r = pd.DataFrame(rows, columns=["start", "end", "app", "flag"]).sort_values("start", kind="mergesort")
    user = ~(r["app"].str.contains(ds.NON_USER_APP) | r["app"].str.contains(ds.LOCKSCREEN_FEED_APP))
    r = r[user.to_numpy()]
    return _rows("app", "in_front", r["start"].to_numpy(), r["end"].to_numpy(), app=r["app"].to_numpy(), flag=r["flag"].to_numpy())


CHAIN_COLS = ["start", "end", "duration_s", "n_segments", "n_nodes", "n_apps", "first_app", "last_app", "path",
              "start_logged", "end_logged"]


def chain_track(app):
    """App chains: runs of user-app in-front segments that hand over to each other within HANDOVER_SECONDS.
    A node is a maximal run of segments of the same app (an app moving between its own screens logs
    Paused / Resumed pairs under one name: the app in front does not change), so n_nodes - 1 is the number of app
    transitions. Only the two ends of a chain matter:
      start_logged  the chain begins with a Resumed (False: it begins with a pause that has no start)
      end_logged    the chain ends with a Paused (False: the last app was never paused; the chain then ends at
                    that app's Resumed, its last logged sign, and nothing is granted beyond it)
    path: the apps in order, at most 8 named."""
    if not len(app):
        return pd.DataFrame(columns=CHAIN_COLS)
    a = app.sort_values("start", kind="mergesort")
    st, en = a["start"].to_numpy(), a["end"].to_numpy().copy()
    ap, fl = a["app"].to_numpy(), a["flag"].to_numpy()
    en[fl == "no pause"] = st[fl == "no pause"]            # the end is unknown: keep only what is logged
    reach = np.maximum.accumulate(en)
    new = np.r_[True, st[1:] - reach[:-1] > HANDOVER_SECONDS]
    cid = np.cumsum(new) - 1
    first = np.where(new)[0]
    last = np.r_[first[1:], len(st)] - 1
    node = new | np.r_[True, ap[1:] != ap[:-1]]
    g = pd.DataFrame(dict(c=cid, app=ap, node=node))
    n_nodes = g.groupby("c")["node"].sum().to_numpy()
    n_apps = g.groupby("c")["app"].nunique().to_numpy()
    nodes = g[g["node"]]
    path = nodes.groupby("c")["app"].agg(lambda v: " > ".join(v.iloc[:8]) + (" > ..." if len(v) > 8 else "")).to_numpy()
    end = np.maximum.reduceat(en, first)
    return pd.DataFrame(dict(start=st[first], end=end, duration_s=end - st[first], n_segments=last - first + 1,
                             n_nodes=n_nodes, n_apps=n_apps, first_app=ap[first], last_app=ap[last], path=path,
                             start_logged=fl[first] != "no start", end_logged=fl[last] != "no pause"))[CHAIN_COLS]


def build(ev, x=None, sig=None):
    """Returns (profile, app): profile holds the silence and key tracks, app the app track."""
    x = ds.interval_labels(ev, sig) if x is None else x
    if x is None:
        return pd.DataFrame(columns=COLS), pd.DataFrame(columns=COLS)
    car = car_track(ev)
    prof = pd.concat([silence_track(ev["t"].to_numpy()), key_track(ev, x), car, service_track(ev, x, car),
                      pip_track(ev, car)], ignore_index=True)
    return prof.sort_values(["start", "track"], kind="mergesort")[COLS], app_track(ev)[COLS]
