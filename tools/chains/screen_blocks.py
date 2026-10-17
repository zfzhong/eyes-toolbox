"""screen_blocks.py <category folder>: inside each Power Cycle, the alternation of ScreenOn and ScreenOff blocks (David, 10-16),
event order only, no thresholds. Run power_cycles.py first.
Events (Chronicle's names) vs blocks (periods): a ScreenOn block runs from a Screen Interactive event to the next Screen
Non-interactive event; a ScreenOff block the reverse.
Lost blocks (David, 10-16: not "Unknown", "since we know something: some events (likely Paused) are lost"): where the log
contradicts itself nothing is placed, and the block lists the events that must be missing (column lost) (David, 10-16: "In theory, we dont know what happened
between two ScreenOn events. We are sure: some events got lost. They might be screen off, they might be shutdown and then
bootup."):
  (10-16) the boundary is where the app-level construction fails (run_until_fail), chain after chain, not the end of the
  first chain.
  two Screen Interactive in a row      lost: Screen Non-interactive (and the Paused / Stopped of the app still in front)
                                       ScreenOn from the first up to the last event of the app chain that started after it
                                       (end: EventLost - the app on screen certainly lasted that long), then Unknown to the
                                       second. No app chain: Lost from the first.
  two Screen Non-interactive in a row  lost: Screen Interactive (and the Resumed of an app whose chain begins with a Paused)
                                       Lost from the first up to the first event of the app chain that reaches the
                                       second, then ScreenOn (start: EventLost). No app chain: Lost throughout.
  A boot signature inside a Lost block adds the alternative "or Device Shutdown + Bootup".
Unknown remains only where logging had not begun (a LogStart Power Cycle before its first screen event) or a Power Cycle has
no screen events at all.
  (app chain = maximal run of app events that each follow from the ones before; see app_chains)
  before the first screen event        after Bootup: ScreenOn if that event is a Screen Non-interactive (the boot's screen-on
                                       came first), ScreenOff if it is a Screen Interactive; after LogStart: Unknown (the
                                       screen state before logging began is not known)
Each Unknown block keeps what is inside it for review: uses (Activity Resumed / Paused, Keyguard Hidden, User Interaction),
lock-screen events, and boot signatures (Settings Paused with no Resumed: FallbackHome, pattern A1) - the triplets may tell
a lost screen-off from a lost power cycle.
Writes <folder>/_review/screen_blocks_<pid>.csv and screen_blocks.tsv."""
import sys, os, glob
TB = os.path.expanduser("~/workspace/eyes-toolbox")
if not os.path.isdir(TB): TB = os.path.expanduser("~/mnt/eyes-toolbox")
sys.path.insert(0, TB)
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chain_core
from eyeslib.states import device_state as ds
folder = os.path.abspath(sys.argv[1]); out = os.path.join(folder, "_review")
ON, OFF = "Screen Interactive", "Screen Non-interactive"
USE = {"Activity Resumed", "Activity Paused", "Keyguard Hidden", "User Interaction"}
APP = {"Activity Resumed", "Activity Paused", "Activity Stopped"}


def app_chains(idx, nm, pk):
    """Split app events (indexes idx, in order) into maximal consistent triplet chains, event order only. A chain goes on
    while each event follows from the ones before: Resumed while the app in front is not pending a Paused, Paused of the
    app in front (or of the one it handed over to), Stopped of a Paused screen. It stops at the first event that does not
    follow, and also when it ended properly (nothing in front, nothing Paused-not-Stopped) and a new Resumed comes.
    Returns a list of (first index, last index)."""
    out = []; i = 0
    while i < len(idx):
        front = pending = None; waiting = {}; started = False; first = last = None
        j = i
        while j < len(idx):
            k = idx[j]; e, x = nm[k], pk[k]; ok = False
            if e == "Activity Resumed":
                if pending is None:
                    if front is not None: pending, front, ok = front, x, True
                    elif not started or any(v > 0 for v in waiting.values()): front, ok = x, True
            elif e == "Activity Paused":
                if x == pending: pending = None; waiting[x] = waiting.get(x, 0) + 1; ok = True
                elif x == front: front = None; waiting[x] = waiting.get(x, 0) + 1; ok = True
            elif e == "Activity Stopped":
                if waiting.get(x, 0) > 0: waiting[x] -= 1; ok = True
            if not ok: break
            started = True; first = k if first is None else first; last = k; j += 1
        if first is None: j = i + 1                     # this event cannot start a chain: skip it
        else: out.append((first, last))
        i = j
    return out

def run_until_fail(idx, nm, pk, lead=("Activity Stopped",)):
    """David, 10-16: "we construct the app level logical chain until we fail". How many app events of idx follow
    logically before the first that does not, with the FIFO triplet queue of chain_core.py (S7-S9 accepted)."""
    return chain_core.walk(idx, nm, pk, lead, stop_at_fail=True)[0]

def chain_end_front(idx, nm, pk):
    """The app still in front (Resumed, not Paused) after the events idx, in order; None if none."""
    front = pending = None
    for k in idx:
        e, x = nm[k], pk[k]
        if e == "Activity Resumed":
            pending, front = (front, x) if front is not None else (pending, x)
        elif e == "Activity Paused":
            if x == pending: pending = None
            elif x == front: front = None
    return front

def blocks_of(t, nm, pk, cyc, ci):
    """t, nm, pk: the Power Cycle's events in order. Returns its ScreenOn / ScreenOff / Unknown blocks."""
    B = []
    scr = [k for k in range(len(nm)) if nm[k] in (ON, OFF)]
    def blk(kind, k0, by0, k1, by1, why="", lost=""):
        seg = slice(k0, k1 + 1); n = nm[seg]; p = pk[seg]
        fallback = int(((n == "Activity Paused") & (p == "com.android.settings")).sum())
        if kind == "EventLost" and fallback: lost = lost + " | or Device Shutdown + Bootup (boot signature inside)"
        B.append(dict(cycle=ci, block=kind, start_t=t[k0], end_t=t[k1], start_by=by0, end_by=by1, why=why, lost=lost,
                      uses=int(np.isin(n, list(USE)).sum()), keyguard_shown=int((n == "Keyguard Shown").sum()),
                      keyguard_hidden=int((n == "Keyguard Hidden").sum()), settings_paused=fallback))
    if not scr:
        blk("Unknown", 0, cyc.start, len(nm) - 1, cyc.end, "no screen events")
        return B
    first = nm[scr[0]]
    if scr[0] > 0:
        if cyc.start == "Bootup":
            blk("ScreenOn" if first == OFF else "ScreenOff", 0, "Bootup", scr[0], first)
        else:
            blk("Unknown", 0, cyc.start, scr[0], first, "screen state before logging began")   # nothing is lost here: logging had not begun
    for a_, b_ in zip(scr, scr[1:]):
        ea, eb = nm[a_], nm[b_]
        if ea == ON and eb == OFF:   blk("ScreenOn", a_, ON, b_, OFF)
        elif ea == OFF and eb == ON: blk("ScreenOff", a_, OFF, b_, ON)
        elif ea == ON:
            # Two screen-ons: a Screen Non-interactive(infer) lies between them (David, 10-17: the chain goes on as long as
            # the front screen continues logically; an inferred event has no time, only the window between two real
            # events; that window is the EventLost block). Activity needs the screen on, so it lies after the last
            # Resumed r. If the app in front at r is then Paused with no Resumed after it, the screen-off is what paused
            # it: the window is the step just before that Paused. Otherwise it is after the last app event, and that app's
            # Paused(infer) / Stopped(infer) lie in the same window (4075_C01, Minecraft).
            ai = [k for k in range(a_ + 1, b_) if nm[k] in APP]
            rs = [j for j, k in enumerate(ai) if nm[k] == "Activity Resumed"]
            if rs:
                r = rs[-1]; fr = chain_end_front(ai[:r + 1], nm, pk)
                pj = next((j for j in range(r + 1, len(ai)) if nm[ai[j]] == "Activity Paused" and pk[ai[j]] == fr), None)
                if pj is not None:                      # the screen-off paused the app in front: tight window
                    w0, w1 = ai[pj - 1], ai[pj]
                    blk("ScreenOn", a_, ON, w0, "EventLost", "two Screen Interactive")
                    blk("EventLost", w0, "EventLost", w1, "EventLost", "two Screen Interactive", "Screen Non-interactive(infer)")
                    blk("ScreenOff", w1, "EventLost", b_, ON, "two Screen Interactive")
                else:
                    w0 = ai[-1]
                    lost = (f"Paused(infer) {fr}, Stopped(infer) {fr}, " if fr else "") + "Screen Non-interactive(infer)"
                    blk("ScreenOn", a_, ON, w0, "EventLost", "two Screen Interactive")
                    blk("EventLost", w0, "EventLost", b_, ON, "two Screen Interactive", lost)
            else:
                blk("EventLost", a_, ON, b_, ON, "two Screen Interactive, no app chain between", "Screen Non-interactive(infer)")
        else:
            # Two screen-offs: a Screen Interactive(infer) lies between them. After the first screen-off come the Paused /
            # Stopped of the apps it sent away; the first Resumed needs the screen on. The window is between the last of
            # those and that Resumed; from the Resumed the screen is on up to the second screen-off (its app events chain
            # on, with inferred events where some are lost).
            ai = [k for k in range(a_ + 1, b_) if nm[k] in APP]
            r1 = next((j for j, k in enumerate(ai) if nm[k] == "Activity Resumed"), None)
            if r1 is not None:
                w0 = ai[r1 - 1] if r1 > 0 else a_; w1 = ai[r1]
                if w0 != a_: blk("ScreenOff", a_, OFF, w0, "EventLost", "two Screen Non-interactive")
                if w1 != w0:
                    blk("EventLost", w0, OFF if w0 == a_ else "EventLost", w1, "EventLost", "two Screen Non-interactive", "Screen Interactive(infer)")
                blk("ScreenOn", w1, "EventLost", b_, OFF, "two Screen Non-interactive")
            else:
                blk("EventLost", a_, OFF, b_, OFF, "two Screen Non-interactive, no app chain between", "Screen Interactive(infer)")
    last = scr[-1]
    if last < len(nm) - 1 or len(scr) == 1:
        blk("ScreenOn" if nm[last] == ON else "ScreenOff", last, nm[last], len(nm) - 1, cyc.end)
    return B

rows = []
for f in sorted(glob.glob(os.path.join(folder, "processed", "*_sorted_uniq_reordered.csv"))):
    pid = os.path.basename(f).split("_Chronicle")[0]
    pf = os.path.join(out, f"power_cycles_{pid}.csv")
    if not os.path.exists(pf): continue
    P = pd.read_csv(pf)
    ev = ds.load_events(f); t = ev.t.to_numpy(); nm = ev.name.to_numpy(); pk = ev.app_package_name.astype(str).to_numpy()
    tz = pd.read_csv(f, usecols=["timezone"], nrows=1).timezone.iloc[0] or "UTC"
    allB = []
    for ci, c in P.iterrows():
        i0, i1 = np.searchsorted(t, c.start_t - 1e-3, "left"), np.searchsorted(t, c.end_t + 1e-3, "right")   # CSV rounding
        if i1 <= i0: continue
        Bs = blocks_of(t[i0:i1], nm[i0:i1], pk[i0:i1], c, ci)
        allB += Bs
    Bdf = pd.DataFrame(allB); Bdf["h"] = (Bdf.end_t - Bdf.start_t) / 3600
    # block id (David, 10-17): <file>/P<Power Cycle>/<block start, local time to the ms>. The start time is the block's
    # local id inside its Power Cycle: splitting a block later gives new start times that cannot collide, and blocks
    # sort by it. Two blocks starting at the same instant (a 0-second block, e.g. the boot's ScreenOn) get the type added.
    loc = pd.to_datetime((Bdf.start_t * 1000).round().astype("int64"), unit="ms", utc=True).dt.tz_convert(tz).dt.strftime("%Y-%m-%dT%H:%M:%S.%f").str[:-3]
    bid = [f"{pid}/P{c + 1}/{l}" for c, l in zip(Bdf.cycle, loc)]
    dup = pd.Series(bid).duplicated(keep=False).to_numpy()
    bid = [b + (f"-{k}" if d else "") for b, d, k in zip(bid, dup, Bdf.block)]
    n = pd.Series(bid).groupby(bid).cumcount().to_numpy()   # still equal (two 0-second blocks of one type): -2, -3 ...
    Bdf.insert(0, "block_id", [b + (f"-{m + 1}" if m else "") for b, m in zip(bid, n)])
    Bdf.to_csv(os.path.join(out, f"screen_blocks_{pid}.csv"), index=False)
    k = Bdf.block.value_counts(); h = Bdf.groupby("block").h.sum()
    lst = Bdf[Bdf.block == "EventLost"]
    rows.append(dict(pid=pid, power_cycles=len(P), blocks=len(Bdf), ScreenOn=int(k.get("ScreenOn", 0)), ScreenOff=int(k.get("ScreenOff", 0)),
                     Lost=int(k.get("EventLost", 0)), Unknown=int(k.get("Unknown", 0)), ScreenOn_h=round(h.get("ScreenOn", 0), 1), ScreenOff_h=round(h.get("ScreenOff", 0), 1),
                     Lost_h=round(h.get("EventLost", 0), 1), Unknown_h=round(h.get("Unknown", 0), 1), lost_with_boot_signature=int((lst.settings_paused > 0).sum())))
S = pd.DataFrame(rows); S.to_csv(os.path.join(out, "screen_blocks.tsv"), sep="\t", index=False)
print(S.to_string(index=False))
T = S.drop(columns="pid").sum()
span = T.ScreenOn_h + T.ScreenOff_h + T.Lost_h + T.Unknown_h
print(f"\nALL: {int(T.power_cycles)} Power Cycles -> {int(T.blocks):,} blocks: ScreenOn {int(T.ScreenOn):,} ({T.ScreenOn_h:,.0f} h), ScreenOff {int(T.ScreenOff):,} ({T.ScreenOff_h:,.0f} h), EventLost {int(T.Lost):,} ({T.Lost_h:,.0f} h = {100 * T.Lost_h / span:.1f}%), Unknown {int(T.Unknown):,} ({T.Unknown_h:,.1f} h); EventLost blocks with a boot signature inside: {int(T.lost_with_boot_signature)}")
