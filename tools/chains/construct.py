"""construct.py: the activity chain construction (David, 10-17: "our goal is to have a good activity chain construction
algorithm"). Event order only, no time thresholds.

Two chains are built per Power Cycle and read against each other:
  activity chain   the FIFO triplet queue per app (chain_core.py): Resumed -> Paused -> Stopped, with returning screens,
                   several screens per app (S7-S9), duplicates; where an event must be missing it is inferred
                   (Paused(infer), Resumed(infer), PausedOrKilled(infer)) with the window between two real events.
  device chain     Screen Interactive -> Keyguard Hidden -> Screen Non-interactive -> Keyguard Shown -> ... (keyguard
                   steps absent on devices with no lock); a repeated screen event means a screen event was lost.
Where they meet (Android's own logic, not rules about time):
  C1  a lost screen-off pauses the app in front: in two screen-ons in a row, the lost Screen Non-interactive lies in the
      window of the front screen's inferred Paused (8862_C01: Settings never Paused, 75 days); if the front app Pauses
      and nothing comes to the front after it, that Paused is the screen-off's (4767_C01); otherwise it lies after the
      last event before the second screen-on (4075_C01). Events in the second screen-on's own millisecond are its burst.
  C2  a lost screen-on: in two screen-offs in a row, it lies after the first screen-off's own aftermath (the Paused /
      Stopped / Keyguard Shown it causes) and before the first sign of the screen on: a Keyguard Hidden, a Resumed, or
      an app's inferred Resumed.
  C3  the screen cannot be on with nothing in front: if the app in front Pauses and the next device event is a
      screen-off with nothing Resumed between (Android writes the screen-off before the Paused it causes), the stretch
      from that Paused to the screen-off is EventLost (4661_C01, 37 days).
Blocks: ScreenOn / ScreenOff between screen events; EventLost = the window of a lost screen event."""
import collections, numpy as np
import chain_core

ON, OFF, KS, KH = "Screen Interactive", "Screen Non-interactive", "Keyguard Shown", "Keyguard Hidden"
APP = {"Activity Resumed", "Activity Paused", "Activity Stopped"}
BACKGROUND = {"Standby Bucket Changed", "Notification Interruption", "Notification Seen", "Configuration Change",
              "Foreground Service Start", "Foreground Service Stop"}
USE = {"Activity Resumed", "Activity Paused", "Keyguard Hidden", "User Interaction"}

def blocks(t, nm, pk, cyc, ci):
    n_ev = len(nm); B = []
    idx = [k for k in range(n_ev) if nm[k] in APP]
    inf = []; chain_core.walk(idx, nm, pk, ("Activity Paused", "Activity Stopped"), inferred=inf)
    lastev = {}; prev_of = {}                          # each app event -> the same app's previous event
    for k in idx:
        prev_of[k] = lastev.get(pk[k]); lastev[pk[k]] = k
    def stopped_after(app, b):                         # the app's next event after b is a Stopped: an ordinary hand-over
        nx = next((k for k in idx if k > b and pk[k] == app), None)
        return nx is not None and nm[nx] == "Activity Stopped"
    ACC = set(APP) | {ON, OFF, KS, KH}                 # events that say what is on screen
    def prev_nonbg(b):                                 # the last event before b that the chain accounts for
        return next((k for k in range(b - 1, -1, -1) if nm[k] in ACC), 0)
    # an inferred Paused is revealed by event b (the hand-over Resumed, the Paused of an app never Resumed, the Stopped);
    # the front screen goes on logically up to the event before b: the loss lies between the two (David, 10-16:
    # "construct the app level logical chain until we fail ... Where it fails, it's the start of the EventLost block")
    paused_inf = sorted((prev_nonbg(b), app) for a, b, ev, app in inf
                        if ev in ("Activity Paused", "PausedOrKilled") and not stopped_after(app, b))
    lost_inf = sorted(set(paused_inf) | {(prev_nonbg(b), app) for a, b, ev, app in inf if ev == "Activity Resumed"})
    resumed_inf = sorted((a if a is not None else b, b, app) for a, b, ev, app in inf if ev == "Activity Resumed")
    nonbg = lambda k0, k1: [k for k in range(k0, k1) if nm[k] not in BACKGROUND]
    def nxt(k, hi):                                    # the first non-background event after k, up to hi
        return next((kk for kk in range(k + 1, hi + 1) if nm[kk] not in BACKGROUND), hi)
    def nxt_acc(k, hi):
        return next((kk for kk in range(k + 1, hi + 1) if nm[kk] in ACC), hi)
    def blk(kind, k0, by0, k1, by1, why="", lost=""):
        seg = slice(k0, k1 + 1); n = nm[seg]; p = pk[seg]
        fb = int(((n == "Activity Paused") & (p == "com.android.settings")).sum())
        if kind == "EventLost" and fb: lost += " | or Device Shutdown + Bootup (boot signature inside)"
        B.append(dict(cycle=ci, block=kind, start_t=t[k0], end_t=t[k1], start_by=by0, end_by=by1, why=why, lost=lost,
                      uses=int(np.isin(n, list(USE)).sum()), keyguard_shown=int((n == KS).sum()),
                      keyguard_hidden=int((n == KH).sum()), settings_paused=fb))
    def front_at(k0, k1):                              # the app in front after the app events in [k0, k1)
        return chain_core_front([k for k in range(k0, k1) if nm[k] in APP])
    def chain_core_front(ai):
        front = pending = None
        for k in ai:
            e, x = nm[k], pk[k]
            if e == "Activity Resumed": pending, front = (front, x) if front is not None else (pending, x)
            elif e == "Activity Paused":
                if x == pending: pending = None
                elif x == front: front = None
        return front
    def screen_on(lo, lo_by, hi, end, why):
        """Screen on from event lo up to the screen-off hi.
        In a stretch made from a contradiction (why set), a front screen that never closes (its Paused lost and no
        Stopped after the take-over) is where a screen-off and a screen-on were lost too (C1): EventLost over its window.
        C3: after the last Resumed, the app in front Pauses (and maybe Stops) and the screen-off follows with no Keyguard
        Shown between: nothing is in front from that Paused (Android writes the screen-off before the Paused it causes)."""
        if why:
            pi = [(a, app) for a, app in lost_inf if lo <= a < hi]
            if pi:
                w0 = pi[0][0]; w1 = nxt_acc(w0, hi)  # = the revealing event
                blk("ScreenOn", lo, lo_by, w0, "EventLost", why)
                if w1 > w0: blk("EventLost", w0, "EventLost", w1, "EventLost", why,
                                f"Paused(infer) or Resumed(infer) {pi[0][1]}, Screen Non-interactive(infer), Screen Interactive(infer)")
                if w1 < hi: return screen_on(w1, "EventLost", hi, end, why)
                return
        body = nonbg(lo, hi)
        rs = [k for k in body if nm[k] == "Activity Resumed"]
        if rs and why:                                 # only where the screen log contradicts itself (EventLost definition)
            tail = [k for k in body if k > rs[-1]]
            ps = [k for k in tail if nm[k] == "Activity Paused" and pk[k] == pk[rs[-1]]]
            if ps and all(nm[k] in ("Activity Paused", "Activity Stopped") for k in tail) and abs(t[ps[0]] - t[hi]) > 1e-3:
                p = ps[0]
                blk("ScreenOn", lo, lo_by, p, "EventLost", why)
                blk("EventLost", p, "EventLost", hi, OFF, (why + ": " if why else "") + "nothing in front from a Paused to the screen-off",
                    f"Resumed(infer) of the next screen, or Screen Non-interactive(infer) at the {pk[p]} Paused")
                return
        blk("ScreenOn", lo, lo_by, hi, end, why)
    scr = [k for k in range(n_ev) if nm[k] in (ON, OFF)]
    if not scr:
        blk("Unknown", 0, cyc.start, n_ev - 1, cyc.end, "no screen events"); return B
    if scr[0] > 0:
        if cyc.start == "Bootup": blk("ScreenOn" if nm[scr[0]] == OFF else "ScreenOff", 0, "Bootup", scr[0], nm[scr[0]])
        else: blk("Unknown", 0, cyc.start, scr[0], nm[scr[0]], "screen state before logging began")
    for a_, b_ in zip(scr, scr[1:]):
        ea, eb = nm[a_], nm[b_]
        if ea == ON and eb == OFF: screen_on(a_, ON, b_, OFF, "")
        elif ea == OFF and eb == ON: blk("ScreenOff", a_, OFF, b_, ON)
        elif ea == ON:                                  # C1: a Screen Non-interactive is lost
            why = "two Screen Interactive"
            burst = lambda k: abs(t[k] - t[b_]) < 1e-3
            pi = [(a, app) for a, app in paused_inf if a_ <= a < b_ and not burst(a)]
            body = [k for k in nonbg(a_ + 1, b_) if not burst(k)]
            if pi:                                      # the front screen's Paused is lost: the screen-off with it
                w0 = pi[0][0]; w1 = nxt_acc(w0, b_)
                lost = f"Paused(infer) {pi[0][1]}, Screen Non-interactive(infer)"
                more = any(nm[k] == "Activity Resumed" for k in range(w1, b_) if not burst(k))
                if more: lost += ", Screen Interactive(infer)"
                blk("ScreenOn", a_, ON, w0, "EventLost", why)
                if w1 > w0: blk("EventLost", w0, "EventLost", w1, "EventLost", why, lost)
                if more: blk("ScreenOn", w1, "EventLost", b_, ON, why + " (activity after the lost screen-off and screen-on)")
                else: blk("ScreenOff", w1, "EventLost", b_, ON, why)
                continue
            ps = [k for k in body if nm[k] == "Activity Paused"]
            if ps and not any(nm[k] == "Activity Resumed" for k in body if k > ps[-1]) and front_at(a_, ps[-1]) in (None, pk[ps[-1]]):
                p = ps[-1]                              # the front app Paused, nothing after: the screen-off's Paused
                blk("ScreenOn", a_, ON, p, "Screen Non-interactive(infer)", why)
                blk("ScreenOff", p, "Screen Non-interactive(infer)", b_, ON, why); continue
            w0 = body[-1] if body else a_
            fr = front_at(a_, w0 + 1)
            if w0 != a_: blk("ScreenOn", a_, ON, w0, "EventLost", why)
            blk("EventLost", w0, ON if w0 == a_ else "EventLost", b_, ON, why,
                (f"Paused(infer) {fr}, Stopped(infer) {fr}, " if fr else "") + "Screen Non-interactive(infer)")
        else:                                           # C2: a Screen Interactive is lost
            why = "two Screen Non-interactive"
            body = nonbg(a_ + 1, b_)
            # device chain OFF -> KS -> ON: once the first screen-off's Keyguard Shown is logged, the screen comes on after it;
            # what comes before it (Paused, Stopped, an app Resumed under the lock) is still that screen-off
            ks = next((k for k in body if nm[k] == KS), None)
            ev = next((k for k in body if nm[k] in (KH, "Activity Resumed") and (ks is None or k > ks)), None)
            ri = [b for a, b, app in resumed_inf if a_ < b < b_]
            ri = [b for b in ri if ks is None or b > ks]
            if ri and (ev is None or ri[0] < ev): ev = ri[0]
            # the first screen-off's aftermath (its Paused / Stopped, then Keyguard Shown: the cycle ON -> KH -> OFF -> KS -> ON)
            # is still screen-off; the lost Screen Interactive lies after it
            aft = [k for k in body if (ev is None or k < ev) and (nm[k] in ("Activity Paused", "Activity Stopped", KS) or (ks is not None and k <= ks))]
            if ev is None:
                w0 = aft[-1] if aft else a_
                if w0 != a_: blk("ScreenOff", a_, OFF, w0, "EventLost", why)
                late = [pk[k] for k in range(b_ + 1, min(b_ + 6, n_ev)) if nm[k] == "Activity Paused" and
                        any(r == k for _, r, _a in resumed_inf)]
                blk("EventLost", w0, OFF if w0 == a_ else "EventLost", b_, OFF, why + ", no screen-on evidence between",
                    "Screen Interactive(infer)" + "".join(f", Resumed(infer) {p}" for p in late)); continue
            w0 = aft[-1] if aft else a_
            if w0 != a_: blk("ScreenOff", a_, OFF, w0, "EventLost", why)
            if ev > w0: blk("EventLost", w0, OFF if w0 == a_ else "EventLost", ev, "EventLost", why, "Screen Interactive(infer)")
            screen_on(ev, "EventLost", b_, OFF, why)
    last = scr[-1]
    if last < n_ev - 1 or len(scr) == 1:
        blk("ScreenOn" if nm[last] == ON else "ScreenOff", last, nm[last], n_ev - 1, cyc.end)
    return B
