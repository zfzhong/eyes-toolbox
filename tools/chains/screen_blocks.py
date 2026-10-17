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
import chain_core, construct
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

BACKGROUND = {"Standby Bucket Changed", "Notification Interruption", "Notification Seen", "Configuration Change"}

def front_break(ai, nm, pk):
    """David, 10-17 (8862_C01): the construction stops where the front screen cannot continue. Walk the app events ai
    in order, keeping the app in front; return the first break, or None:
      ("lost", j)  the app in front never Pauses: another app Resumes and the front app's next event is not its Paused
                   before a further Resumed (no hand-over); its Paused is lost after its last event ai[j];
      ("off", j)   the app in front Pauses at ai[j] and nothing Resumes after it: what paused it was a screen-off;
      ("orphan", j) an app that was not Resumed here is Paused at ai[j] (after the front app): its Resumed is lost."""
    front = None; fpaused = False; lastj = {}
    rpos = [j for j, k in enumerate(ai) if nm[k] == "Activity Resumed"]
    for j, k in enumerate(ai):
        e, x = nm[k], pk[k]
        if e == "Activity Resumed":
            if front is not None and front != x and not fpaused:
                nr = next((r for r in rpos if r > j), len(ai))              # the next Resumed after this one
                fp = next((jj for jj in range(j + 1, nr) if pk[ai[jj]] == front and nm[ai[jj]] == "Activity Paused"), None)
                if fp is None:
                    nf = next((jj for jj in range(j + 1, len(ai)) if pk[ai[jj]] == front), None)
                    if nf is None or nm[ai[nf]] != "Activity Stopped":
                        return ("lost", lastj.get(front, j - 1))   # no hand-over: the front screen breaks
                    # else the front screen is Stopped after the take-over (R(B) .. S(A)): an ordinary hand-over
                    # with only its Paused lost (Paused(infer), 4104_C01 YouTube -> home screen); no screen event is lost
            front, fpaused = x, False
        elif e == "Activity Paused" and x == front:
            fpaused = True
            if not any(r > j for r in rpos): return ("off", j)
        elif e == "Activity Paused" and x not in lastj and front is not None and front != x:
            return ("orphan", j)                         # an app never Resumed here is Paused: its Resumed is lost
        lastj[x] = j
    return None

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
    def segment(lo, lo_by, hi, end, why, allow_lost=True):
        """The screen is on from event lo; event hi is a screen-on (end == ON: a screen-off is lost before it) or a
        screen-off (end == OFF: consistent unless the front screen breaks). At the first break of the front screen
        (front_break) the screen-off(infer) lies in the window after the front screen's last event; if a Resumed comes
        after the window the screen came back on in it (Screen Interactive(infer)) and the rest is checked the same way.
        Used only inside a contradiction (two screen-ons or two screen-offs in a row), where screen events are lost
        anyway: each break of the front screen hosts a lost screen-off (and a screen-on if activity follows). A break
        in the middle of use gives a window of a few events; a break before a long silence gives the long window."""
        ai = [k for k in range(lo, hi) if nm[k] in APP and abs(t[k] - t[hi]) > 1e-3]   # the start's own Resumed counts;
        br = front_break(ai, nm, pk) if ai else None                                  # events in the closing event's
                                                                                      # millisecond are its burst (a boot)
        if br is not None and br[0] == "lost" and not allow_lost:
            br = None
            for jj in range(len(ai)):                   # only an "off" break counts here
                if nm[ai[jj]] == "Activity Paused" and not any(nm[k] == "Activity Resumed" for k in ai[jj + 1:]) \
                        and chain_end_front(ai[:jj], nm, pk) == pk[ai[jj]]:
                    br = ("off", jj); break
        if br is None:
            if end == OFF: blk("ScreenOn", lo, lo_by, hi, OFF, why); return
            if not ai: blk("EventLost", lo, lo_by, hi, ON, why + ", no app chain between", "Screen Non-interactive(infer)"); return
            fr = chain_end_front(ai, nm, pk); w0 = ai[-1]     # nothing breaks: after the last app event (4075_C01)
            blk("ScreenOn", lo, lo_by, w0, "EventLost", why)
            blk("EventLost", w0, "EventLost", hi, ON, why, (f"Paused(infer) {fr}, Stopped(infer) {fr}, " if fr else "") + "Screen Non-interactive(infer)")
            return
        kind, j = br
        if kind == "off":                               # the screen-off paused the front app: the front screen continues
            p = ai[j]                                   # up to that Paused, and the screen-off is just before it
            blk("ScreenOn", lo, lo_by, p, "Screen Non-interactive(infer)", why)
            if end == ON: blk("ScreenOff", p, "Screen Non-interactive(infer)", hi, ON, why)
            else: blk("EventLost", p, "Screen Non-interactive(infer)", hi, OFF, why + ", no app chain between", "Screen Interactive(infer)")
            return
        elif kind == "orphan":                          # the app was Resumed (lost) after the last event before its Paused
            w0, w1 = (ai[j - 1] if j > 0 else lo), ai[j]; fr = pk[w1]
            fa = chain_end_front(ai[:j], nm, pk)
            lost = (f"Paused(infer) {fa}, " if fa else "") + f"Screen Non-interactive(infer), Resumed(infer) {fr}"
        else:                                           # the front app's Paused is lost after its last event; the window
            w0 = ai[j]; fr = pk[w0]                     # ends at the next event that is not background (standby bucket,
            w1 = next((k for k in range(w0 + 1, hi)     # notification, configuration change) and not a Stopped (the
                       if nm[k] not in BACKGROUND and nm[k] != "Activity Stopped"), hi)   # Stopped of earlier screens)
            lost = f"Paused(infer) {fr}, Screen Non-interactive(infer)"
        more = kind == "orphan" or any(nm[k] == "Activity Resumed" for k in range(w1, hi) if abs(t[k] - t[hi]) > 1e-3)
        if more: lost += ", Screen Interactive(infer)"
        blk("ScreenOn", lo, lo_by, w0, "EventLost", why)
        if w1 > w0: blk("EventLost", w0, "EventLost", w1, "EventLost", why, lost)
        if more:
            segment(w1, "EventLost", hi, end, why)
        elif end == ON:
            blk("ScreenOff", w1, "EventLost", hi, ON, why)
        else:                                           # screen off from w1, and the end is a screen-off: a screen-on is lost too
            blk("EventLost", w1, "EventLost", hi, OFF, why + ", no app chain between", "Screen Interactive(infer)")
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
            # Two screen-ons (David, 10-17): a Screen Non-interactive(infer) lies between them, where the front screen first
            # cannot continue (its lost Paused and the screen-off that paused it belong together); see segment().
            segment(a_, ON, b_, ON, "two Screen Interactive")
        else:
            # Two screen-offs: a Screen Interactive(infer) lies between them. After the first screen-off come the Paused /
            # Stopped of the apps it sent away; the first Resumed needs the screen on: the window is between them. From
            # that Resumed the screen is on, until the front screen breaks (segment) or the second screen-off.
            ai = [k for k in range(a_ + 1, b_) if nm[k] in APP]
            r1 = next((j for j, k in enumerate(ai) if nm[k] == "Activity Resumed"), None)
            if r1 is not None:
                w0 = ai[r1 - 1] if r1 > 0 else a_; w1 = ai[r1]
                if w0 != a_: blk("ScreenOff", a_, OFF, w0, "EventLost", "two Screen Non-interactive")
                if w1 != w0:
                    blk("EventLost", w0, OFF if w0 == a_ else "EventLost", w1, "EventLost", "two Screen Non-interactive", "Screen Interactive(infer)")
                segment(w1, "EventLost", b_, OFF, "two Screen Non-interactive")
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
        Bs = construct.blocks(t[i0:i1], nm[i0:i1], pk[i0:i1], c, ci)   # 10-17: activity chain + device chain (construct.py)
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
