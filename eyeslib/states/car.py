"""Android Auto (car projection) as its own state, apart from phone screen time and glances
(pattern book addendum E6; David 10-13: "the android auto is a separate category").

Tested on the Samsung test phone in a car (10-13, tests 1a-1f):
  - While the phone projects to the car, Android logs no screen-off: from plugging in to the end
    the log reads as one long screen-on. Apps on the car screen come to the front in the same,
    single foreground track as the phone's own apps.
  - Everything on the car screen is an activity named GhostActivity, under the app that draws it:
    Maps, Android Auto itself (its launcher, dialer, messages, "call ended"), the Google app
    (Gemini voice). Chronicle loses class names, EyesApp keeps them.
  - The phone's own use during projection is bounded by Keyguard Hidden ... Shown. A look at the
    locked phone leaves nothing (1b), or at most a Notification Seen (1f).
  - The end (unplugging, or the car turned off) logs Screen Non-interactive and Interactive in the
    same second; the phone screen then stays on, locked, for 5-18 s. Not a glance.
  - Calls from or answered on the car: the call service runs, the phone's call screen opens and
    closes in the same second (eyeslib.states.calls handles them as calls).

  projection  eyeslib.states.profile.car_track (rule of 10-07): from the map appearing on the car
              screen after Android Auto connects, to Android Auto's service stop beside a Maps
              service stop. (A first rule of 10-13, "its services running", ran on for days in A1:
              Android Auto's service often never logs its stop.)
  period      the whole projection is the Android Auto period; what the car screen showed does
              not matter (David 10-13: "we just put them into the android auto period").
  phone use   inside it, only the phone's own use is screen time: the phone unlocked (Keyguard
              Hidden ... Shown), and the app in front not a car screen (GhostActivity, unless the
              same app's own activity is resumed then; without class names, any app). Android
              Auto's own package is never phone use.
  after       the screen-on at a projection's end (within EDGE_S), up to the next screen-off,
              when nothing unlocks the phone: part of the car state, not a glance.
"""
import pandas as pd

from eyeslib.core.event_classes import canonical_name

AA = "com.google.android.projection.gearhead"
GHOST = "GhostActivity"
EDGE_S = 3
FGS_START, FGS_STOP = "Foreground Service Start", "Foreground Service Stop"
RESUMED, PAUSED, STOPPED = "Activity Resumed", "Activity Paused", "Activity Stopped"


def _frame(df):
    """t (UTC Timestamps), it (canonical names), pk, cls - sorted by time."""
    names = {v: canonical_name(v) for v in df["interaction_type"].astype(str).unique()}
    out = pd.DataFrame({
        "t": pd.to_datetime(df["event_timestamp"], format="mixed", utc=True, errors="coerce"),
        "it": df["interaction_type"].astype(str).map(names),
        "pk": df["app_package_name"].astype(str),
        "cls": df["app_class_name"].fillna("").astype(str) if "app_class_name" in df.columns else "",
    })
    return out.dropna(subset=["t"]).sort_values("t", kind="mergesort").reset_index(drop=True)


def projections(df):
    """[(start, end)] Android Auto projections in a log frame (app_package_name, interaction_type,
    event_timestamp): the confirmed and likely car periods of eyeslib.states.profile.car_track (rule of
    2026-10-07, from the car tests and A1: the end is Android Auto's service stop beside a Maps service
    stop; the start is the map appearing after Android Auto's connection burst). Its incomplete
    periods (no end mark) are left out: in A1 they run on for days. The 10-13 tests end the same way
    (unplugging stops Maps' service and Android Auto's together)."""
    from eyeslib.states import profile
    d = df if "it" in df.columns else _frame(df)
    ev = pd.DataFrame({"t": d.t.astype("int64").to_numpy() / 1e9, "name": d.it.to_numpy(),
                       "cls": d.cls.to_numpy() if "cls" in d.columns else "", "app_package_name": d.pk.to_numpy()})
    c = profile.car_track(ev)
    c = c[c.kind == "car"].sort_values("start")
    ts = lambda x: pd.Timestamp(round(x * 1000), unit="ms", tz="UTC")
    return [(ts(a), ts(b)) for a, b in zip(c.start, c.end)]


def _intervals(d, keep):
    """{pkg: [(a, b)]}: from each Resumed of a row matching keep to that activity's next Paused or
    Stopped (same package and class)."""
    out, open_ = {}, {}
    for r in d.itertuples(index=False):
        if r.it not in (RESUMED, PAUSED, STOPPED) or not keep(r):
            continue
        key = (r.pk, r.cls)
        if r.it == RESUMED:
            open_.setdefault(key, r.t)
        elif key in open_:
            a = open_.pop(key)
            if r.t > a:
                out.setdefault(r.pk, []).append((a, r.t))
    for (pk, _), a in open_.items():
        out.setdefault(pk, []).append((a, None))
    return out


def tracks(df):
    """What split() needs: projections, the car-screen (ghost) and phone activity intervals per app
    (empty when the log has no class names), the locked intervals, and the screen-ons left after
    projection ends."""
    d = _frame(df)
    proj = projections(d)
    has_cls = bool((d.cls != "").any())
    ghost = _intervals(d, lambda r: r.cls.endswith(GHOST)) if has_cls else {}
    phone = _intervals(d, lambda r: bool(r.cls) and not r.cls.endswith(GHOST) and r.pk in ghost) if has_cls else {}
    kg = d[d.it.isin(["Keyguard Shown", "Keyguard Hidden"])]
    locked, a = [], None
    for t, it in zip(kg.t, kg.it):
        if it == "Keyguard Shown" and a is None:
            a = t
        elif it == "Keyguard Hidden" and a is not None:
            locked.append((a, t)); a = None
    if a is not None:
        locked.append((a, None))
    after = []
    edge = pd.Timedelta(seconds=EDGE_S)
    scr = d[d.it.isin(["Screen Interactive", "Screen Non-interactive", "Keyguard Hidden"])]
    for _, e in proj:
        w = scr[(scr.t >= e - pd.Timedelta(seconds=1)) & (scr.t <= e + edge)]
        on = w[w.it == "Screen Interactive"].t
        if not len(on):
            continue
        s = on.iloc[-1]
        nxt = scr[scr.t > s]
        if not len(nxt) or nxt.it.iloc[0] != "Screen Non-interactive":
            continue                        # unlocked (phone use) or never ended: not ours
        after.append((s, nxt.t.iloc[0]))
    return {"proj": proj, "ghost": ghost, "phone": phone, "locked": locked, "after": after, "classes": has_cls}


def _cut(parts, ivs, keep_inside):
    """Intersect (keep_inside) or subtract parts [(a, b)] with intervals [(a, b|None)]."""
    out = []
    for a, b in parts:
        pieces = []
        cur = a
        for x, y in sorted(ivs, key=lambda v: v[0]):
            y = b if y is None else y
            lo, hi = max(a, x), min(b, y)
            if hi <= lo:
                continue
            if keep_inside:
                pieces.append((lo, hi))
            else:
                if lo > cur:
                    pieces.append((cur, lo))
                cur = max(cur, hi)
        if not keep_inside and cur < b:
            pieces.append((cur, b))
        out.extend(pieces)
    return out


def split(pkg, a, b, tr):
    """(phone_parts, car_parts) of an app row pkg [a, b) (Timestamps)."""
    whole = [(a, b)]
    inproj = _cut(whole, tr["proj"], True)
    if not inproj:
        return whole, []
    if pkg == AA:
        car = inproj
    else:
        ghost = _cut([(x, y if y is not None else b) for x, y in tr["ghost"].get(pkg, [])],
                     tr["phone"].get(pkg, []), False)
        use = _cut(_cut(inproj, tr["locked"], False), ghost, False)    # unlocked, not the car screen
        car = _cut(inproj, use, False)
    phone = _cut(whole, car, False)
    return phone, car


def is_glance_free(start, end, tr):
    """A wake session that overlaps a projection, or is the screen left on at its end, is car
    state, never a glance."""
    if _cut([(start, end)], tr["proj"], True):
        return True
    return any(abs((s - start).total_seconds()) <= 1 for s, _ in tr["after"])
