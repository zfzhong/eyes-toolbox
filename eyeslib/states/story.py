"""Story checker, app level (David, 10-10): walk a file's Activity Resumed / Paused / Stopped events with the app
state (app in front, apps Paused but not Stopped, apps Stopped) and check that every event follows from the
state the earlier events left. Where an event does not fit, the story breaks: the break is recorded with the
event that would have made it fit, the state is repaired as if that event had happened, and a new island starts.

Consistency (one package = one app; Chronicle has no class names, so one app's own screens are Paused /
Resumed in pairs and are folded in):
  A Resumed   the app in front (F) leaves it: F Paused in the same burst (either order), unless nothing is in
              front; if A was Paused but not Stopped, A comes back (a small window or panel ends this way)
  A Paused    A is in front (or is Resumed in the same burst)
  A Stopped   A was Paused and not Resumed since
Later levels (device state, power) are overlaid on these islands; at this level a screen-off is just the
front app Paused + Stopped.
"""
import numpy as np
import pandas as pd

BURST = 1.0            # seconds: events this close may be logged in either order
APP_EVENTS = ["Activity Resumed", "Activity Paused", "Activity Stopped"]
BREAKS = {
    "resume_no_pause_of_front": "A Resumed, but the app in front was not Paused: lost Paused of the app in front",
    "pause_not_in_front": "A Paused, but A was not in front: lost Resumed of A (or A came back with the screen)",
    "pause_twice": "A Paused again without a Resumed between: lost Resumed of A",
    "stop_not_paused_front": "A Stopped while in front: lost Paused of A",
    "stop_unknown": "A Stopped, but A was neither in front nor Paused: lost Resumed + Paused of A, or a second Stopped",
}
BREAKS["resume_twice"] = "A Resumed while already in front, with no Paused or second Resumed of A around it: lost Paused of A"
# An app has several screens (activities) under one package name: it can have more than one Resumed (e.g. Android
# Auto on the car screen and on the phone) and several Paused-but-not-Stopped screens at once. So the state counts,
# per app, its Resumed screens (res) and its Paused-not-Stopped screens (pend); the app is in front while res > 0.


AA = "com.google.android.projection.gearhead"
# During an Android Auto projection there are two screens, each with its own app in front (David, 10-10: "keep two
# tracks: car projection track and phone app track, until the car projection ends"). The log does not say which
# screen an app is on; these go to the car track (navigation, voice, the call screen: the call screen is an
# assumption until the phone-call test).
CAR_APPS = {AA, "com.waze", "com.google.android.apps.maps", "com.google.android.googlequicksearchbox",
            "com.samsung.android.incallui", "com.google.android.dialer", "com.android.incallui"}


def projections(ev):
    """Android Auto projections from Android Auto's own events: the time its foreground service runs (open count
    above zero), kept when Android Auto is Resumed inside it. [(start, end)]"""
    t = ev["t"].to_numpy(); nm = ev["name"].to_numpy(); pk = ev["app_package_name"].astype(str).to_numpy()
    g = pk == AA; out = []; n = 0; s0 = None
    for i in np.where(g & np.isin(nm, ["Foreground Service Start", "Foreground Service Stop"]))[0]:
        if nm[i] == "Foreground Service Start":
            s0 = t[i] if n == 0 else s0; n += 1
        elif n > 0:
            n -= 1
            if n == 0:
                out.append((s0, t[i]))
    res = t[g & (nm == "Activity Resumed")]
    return [(a, b) for a, b in out if ((res >= a) & (res <= b)).any()]


def app_story(ev, stop_limit, proj=None):
    """Returns (events, breaks, islands). events: the app events with track, island number and outcome; breaks:
    one row per break; islands: one row per island. stop_limit: the file's normal Paused -> Stopped delay (its 99%
    point). proj: Android Auto projections [(start, end)] (None: no car track)."""
    m = ev["name"].isin(APP_EVENTS).to_numpy()
    E = ev.loc[m, ["t", "name", "app_package_name"]].reset_index(drop=True)
    t = E.t.to_numpy(); nm = E.name.to_numpy(); pk = E.app_package_name.astype(str).to_numpy(); n = len(E)
    pa = np.array(sorted(proj or []), dtype=float).reshape(-1, 2)
    j = np.searchsorted(pa[:, 0], t, "right") - 1
    in_proj = (j >= 0) & (t <= pa[np.maximum(j, 0), 1] + BURST) if len(pa) else np.zeros(n, bool)
    proj_no = np.where(in_proj, j, -1)
    tr = np.full(n, "phone", dtype=object)
    E["projection"] = proj_no
    at = {}
    for i in range(n):
        at.setdefault((nm[i], pk[i]), []).append(i)
    at = {k: np.array(v) for k, v in at.items()}

    def near(name, app, i, after_only=False):
        v = at.get((name, app))
        if v is None:
            return -1
        lo = np.searchsorted(t[v], t[i] - (0 if after_only else BURST), "left")
        hi = np.searchsorted(t[v], t[i] + BURST, "right")
        c = [j for j in v[lo:hi] if j != i and (j > i or not after_only)]
        return int(c[0]) if c else -1

    res, pend, pause_t = {}, {}, {}           # keyed (track, app)
    front = {"phone": None, "car": None}
    expected, island, cur_proj = set(), 0, -1
    isl = np.zeros(n, dtype=np.int32); out = np.full(n, "", dtype=object); brk = []

    def breaks(i, kind, k):
        nonlocal island
        brk.append(dict(i=i, t=t[i], kind=kind, app=pk[i], track=k, front=front[k] or "", island_before=island))
        island += 1

    def pause(key, when):
        res[key] = max(res.get(key, 0) - 1, 0); pend[key] = pend.get(key, 0) + 1
        if res[key] == 0:
            pause_t[key] = when

    pend_end = {int(x): float(pa[x, 1]) for x in range(len(pa))}
    app_track = {}
    for i in range(n):
        a, e = pk[i], nm[i]
        if proj_no[i] != cur_proj:                  # a projection ended (or began): the car screen is gone / new
            for key in [x for x in list(res) + list(pend) if x[0] == "car"]:
                res.pop(key, None); pend.pop(key, None)
            front["car"] = None; cur_proj = proj_no[i]; app_track = {}
        # which screen: Android Auto -> car; navigation / voice / call screen -> car, unless it takes over from the
        # app on the phone (that app is Paused in the same burst: opened on the phone); others -> phone. Paused and
        # Stopped follow the app's last Resumed.
        if proj_no[i] < 0:
            k = "phone"
        elif e == "Activity Resumed":
            if a == AA:
                k = "car"
            elif a in CAR_APPS:
                f = front["phone"]
                k = "phone" if f is not None and f not in CAR_APPS and near("Activity Paused", f, i) >= 0 else "car"
            else:
                k = "phone"
            app_track[a] = k
        else:
            k = app_track.get(a, "car" if a in CAR_APPS else "phone")
        tr[i] = k
        key = (k, a)
        car_base = k == "car" and res.get(("car", AA), 0) > 0      # Android Auto stays under what the car shows
        if e == "Activity Resumed":
            out[i] = "ok"; f = front[k]
            if f is not None and f != a and res.get((k, f), 0) > 0 and not (car_base and f == AA):
                j2 = near("Activity Paused", f, i, after_only=True)
                if j2 >= 0 and j2 not in expected:
                    expected.add(j2); pause((k, f), t[j2])
                elif k == "car":
                    out[i] = "overlay"                        # over another car app (voice over navigation, call)
                else:
                    breaks(i, "resume_no_pause_of_front", k); pause((k, f), t[i]); out[i] = "break"
            elif f == a and res.get(key, 0) > 0 and a != AA:
                if near("Activity Paused", a, i) < 0 and near("Activity Resumed", a, i) < 0:
                    breaks(i, "resume_twice", k); out[i] = "break"
            if res.get(key, 0) == 0 and pend.get(key, 0) > 0 and f != a and out[i] == "ok":
                out[i] = "back"
            res[key] = res.get(key, 0) + 1; front[k] = a
        elif e == "Activity Paused":
            if i in expected:
                expected.discard(i); out[i] = "ok"
            elif res.get(key, 0) > 0:
                pause(key, t[i]); out[i] = "ok"
                if res[key] == 0 and front[k] == a and near("Activity Resumed", a, i, after_only=True) < 0:
                    front[k] = AA if k == "car" and res.get(("car", AA), 0) > 0 else None
            else:
                breaks(i, "pause_not_in_front", k); pend[key] = pend.get(key, 0) + 1; pause_t[key] = t[i]; out[i] = "break"
        else:
            if pend.get(key, 0) > 0:
                pend[key] -= 1; out[i] = "stop"
                if pend[key] == 0 and res.get(key, 0) == 0 and t[i] - pause_t.get(key, t[i]) > stop_limit:
                    out[i] = "stop_late"
            elif res.get(key, 0) > 0:
                if a == AA and proj_no[i] >= 0 and abs(t[i] - pend_end[int(proj_no[i])]) <= 5:
                    res[key] -= 1; out[i] = "disconnect"           # unplugged: Android Auto Stopped, its Paused not emitted
                else:
                    breaks(i, "stop_not_paused_front", k); res[key] -= 1; out[i] = "break"
                if res[key] == 0 and front[k] == a:
                    front[k] = None
            else:
                breaks(i, "stop_unknown", k); out[i] = "break"
        isl[i] = island
    E["track"] = tr; E["island"] = isl; E["outcome"] = out
    B = pd.DataFrame(brk, columns=["i", "t", "kind", "app", "track", "front", "island_before"])
    I = E.groupby("island").agg(start=("t", "min"), end=("t", "max"), events=("t", "size")).reset_index()
    I["duration_s"] = I.end - I.start
    return E, B, I
