"""chain_logic.py <category folder>: build triplet chains from the ORDER of app events only - no time thresholds (David,
10-15: "construct the triplet chain until we fail ... with perfect activity logs, we will succeed").

Triplet = one app screen's Resumed -> Paused -> Stopped. Events of one package are one app (Chronicle has no class names).
Walk the Activity Resumed / Paused / Stopped events in log order:
  Resumed(B)  - if an app A is in front (Resumed, not Paused): A becomes "pending" (its Paused must come before the next
                Resumed: Android may log R(B) before P(A)); B joins A's chain.
              - else if the chain's last app has Paused but not Stopped: hand-over P(A) R(B) [S(A) later]; B joins the chain.
              - else (last app Paused and Stopped, or no chain): the chain ended properly; B starts a new chain.
              - if a pending A is still not Paused when another Resumed comes: A's Paused is missing -> the chain fails at A.
  Paused(X)   - X pending or in front: its triplet gets its Paused.
              - otherwise X was not in front: the chain fails; X starts a new chain with no start.
  Stopped(X)  - X has a Paused-not-Stopped screen: it gets the Stopped (the latest one).
              - X in front with no Paused (a kill, or a lost Paused): the chain fails at X.
Device state (David, 10-15: a triplet across a screen-off or power-off contradicts the device state):
  Screen Non-interactive  Android pauses and stops the app in front at a screen-off (test phone 10-15), so the chain
                          ends there: the next Resumed starts a new chain. An app still in front (not Paused) when the
                          screen comes back on lost its Paused at the screen-off: the triplet is contradicted and the
                          chain fails. Its Paused, when it comes later, is counted as "late Paused of a contradicted app".
  Device Shutdown / Startup  every chain ends; an app still in front fails the same way.
A chain: start = its first triplet has a real Resumed; end = its last triplet has a real Paused and the chain closed
without a failure. complete = start and end.
EventLost (David, 10-16: "basically we dont want a App chain to contain a EventLost period"): the EventLost blocks from
screen_blocks.py (run it first) cut the chains. At an EventLost block's start the chain ends with EventLost (end_by =
EventLost; the app still in front lost its Paused / Stopped). At its end, the next chain begins with EventLost (start_by =
EventLost; e.g. its Resumed was lost). No chain crosses an EventLost period.
Writes <folder>/_review/logic_chains_<pid>.csv and logic_chains.tsv; prints a summary."""
import sys, os, glob, collections
TB = os.path.expanduser("~/workspace/eyes-toolbox")
if not os.path.isdir(TB): TB = os.path.expanduser("~/mnt/eyes-toolbox")
sys.path.insert(0, TB)
import numpy as np, pandas as pd
from eyeslib.states import device_state as ds
folder = os.path.abspath(sys.argv[1]); out = os.path.join(folder, "_review"); os.makedirs(out, exist_ok=True)

def build(t, nm, pk):
    chains = []; fails = collections.Counter()
    cur = None; front = None; pending = None; waiting = collections.defaultdict(list)
    def new_chain(tri, start):
        nonlocal lost_start
        sb = "EventLost" if lost_start else ("Resumed" if start else "Paused")
        lost_start = False
        return dict(start=start, start_by=sb, end_by="", ok_end=None, n=1, t0=tri["t"], t1=tri["t"], first=tri["app"], last=tri["app"], fail="", lastt=tri)
    def close(c, why):
        if c is None: return
        L = c["lastt"]; c["ok_end"] = (why == "") and L.get("p") is not None; c["fail"] = why
        c["end_by"] = "EventLost" if why == "EventLost" else ("Paused" if c["ok_end"] else "fail")
        c["t1"] = max(c["t1"], L.get("p_t", L["t"])); chains.append(c)
    def add(c, tri):
        c["n"] += 1; c["last"] = tri["app"]; c["lastt"] = tri; c["t1"] = tri["t"]
    contra = set(); off = False; lost_start = False
    def open_apps():
        return [z for z in (front, pending) if z is not None]
    for i in range(len(t)):
        e, x = nm[i], pk[i]
        if e == "EventLost<":                               # an EventLost period begins: the chain ends with EventLost
            for z in open_apps(): contra.add(z["app"])
            close(cur, "EventLost"); cur = None; front = None; pending = None; waiting.clear(); continue
        if e == "EventLost>":                               # it ends: the next chain begins with EventLost
            close(cur, "EventLost" if open_apps() else ""); cur = None; front = None; pending = None
            waiting.clear(); lost_start = True; off = False; continue
        if e in ("Screen Non-interactive", "Device Shutdown", "Device Startup", "Screen Interactive"):
            if e == "Screen Non-interactive":
                off = True; continue
            if e == "Screen Interactive" and not off:
                continue
            # screen back on after a screen-off, or a power event: whatever is still in front lost its Paused
            if open_apps():
                fails["still in front at screen-on / power event: Paused lost"] += 1
                for z in open_apps(): contra.add(z["app"])
                close(cur, "Paused lost at screen-off / power event"); cur = None; front = None; pending = None
            else:
                close(cur, ""); cur = None
            if e != "Screen Interactive": waiting.clear()
            off = False
            continue
        if e == "Activity Resumed" and off and cur is not None and not open_apps():
            close(cur, ""); cur = None                      # the chain ended at the screen-off (front app paused there)
        if e == "Activity Resumed":
            tri = dict(app=x, t=t[i])
            if pending is not None:                         # a second Resumed while A never Paused: A's Paused is missing
                fails["resumed again before the previous app paused"] += 1
                B = cur["lastt"]                            # the app that resumed after A starts the new chain
                close(cur, "missing Paused"); cur = new_chain(B, True); pending = None
                if B.get("p") is not None: cur["lastt"] = B
            if front is not None:                           # R(B) logged before P(A)
                pending = front; add(cur, tri)
            elif cur is not None and cur["lastt"].get("p") is not None and cur["lastt"].get("s") is None:
                add(cur, tri)                               # P(A) R(B): hand-over
            else:
                close(cur, ""); cur = new_chain(tri, True)
            front = tri
        elif e == "Activity Paused":
            if pending is not None and pending["app"] == x:
                tri = pending; pending = None
            elif front is not None and front["app"] == x:
                tri = front; front = None
            elif x in contra:                               # the late Paused of a contradicted triplet
                contra.discard(x); fails["late Paused of a contradicted app"] += 1; continue
            else:                                           # Paused of an app that was not in front
                if not lost_start: fails["paused while not in front"] += 1
                close(cur, "unexpected Paused" if cur is not None else "")
                tri = dict(app=x, t=t[i]); cur = new_chain(tri, False); front = None; pending = None
            tri["p"] = i; tri["p_t"] = t[i]; waiting[x].append(tri)
        elif e == "Activity Stopped":
            if waiting[x]:
                waiting[x].pop()["s"] = i
            elif (front is not None and front["app"] == x) or (pending is not None and pending["app"] == x):
                fails["stopped while in front, no Paused"] += 1
                close(cur, "stopped without Paused")
                cur = None; front = None if (front is not None and front["app"] == x) else front; pending = None
                if front is not None: cur = new_chain(front, True)
            else:
                fails["stray Stopped"] += 1
    close(cur, "end of log")
    return chains, fails

rows = []; allf = collections.Counter()
for f in sorted(glob.glob(os.path.join(folder, "processed", "*_sorted_uniq_reordered.csv"))):
    pid = os.path.basename(f).split("_Chronicle")[0]
    ev = ds.load_events(f)
    a = ev[ev.name.isin(["Activity Resumed", "Activity Paused", "Activity Stopped", "Screen Interactive", "Screen Non-interactive", "Device Shutdown", "Device Startup"])]
    t, nm, pk = list(a.t.to_numpy()), list(a.name.to_numpy()), list(a.app_package_name.astype(str).to_numpy())
    bf = os.path.join(out, f"screen_blocks_{pid}.csv")
    if os.path.exists(bf):                                  # insert the EventLost markers (start after, end before same-time events)
        B = pd.read_csv(bf); B = B[B.block == "EventLost"]
        marks = [(r.start_t + 1e-4, 1, "EventLost<") for r in B.itertuples()] + [(r.end_t - 1e-4, 0, "EventLost>") for r in B.itertuples()]
        for tm, _, m in sorted(marks, reverse=True):
            k = int(np.searchsorted(np.array(t), tm, side="right"))
            t.insert(k, tm); nm.insert(k, m); pk.insert(k, "")
    ch, fails = build(np.array(t), np.array(nm), np.array(pk))
    C = pd.DataFrame(ch).drop(columns=["lastt"])
    C["type"] = np.select([C.start & C.ok_end, ~C.start & C.ok_end, C.start & ~C.ok_end], ["complete", "no start", "no end"], "no start-end")
    C.to_csv(os.path.join(out, f"logic_chains_{pid}.csv"), index=False)
    n = C.type.value_counts()
    r = dict(pid=pid, chains=len(C), **{k: int(n.get(k, 0)) for k in ["complete", "no start", "no end", "no start-end"]})
    r["end EventLost"] = int((C.end_by == "EventLost").sum()); r["start EventLost"] = int((C.start_by == "EventLost").sum())
    r["complete %"] = round(100 * r["complete"] / max(len(C), 1), 1); r["triplets"] = int(C.n.sum())
    r["triplets in complete chains %"] = round(100 * C.n[C.type == "complete"].sum() / max(C.n.sum(), 1), 1)
    rows.append(r); allf.update(fails)
S = pd.DataFrame(rows); S.to_csv(os.path.join(out, "logic_chains.tsv"), sep="\t", index=False)
print(S.to_string(index=False))
T = S[["chains", "complete", "no start", "no end", "no start-end", "triplets", "end EventLost", "start EventLost"]].sum()
tc = sum(r["triplets"] * r["triplets in complete chains %"] / 100 for r in rows)
print(f"\nALL: {int(T.chains):,} chains: complete {int(T.complete):,} ({T.complete / T.chains:.1%}), no start {int(T['no start']):,}, no end {int(T['no end']):,}, no start-end {int(T['no start-end']):,}; triplets {int(T.triplets):,}, in complete chains {tc / T.triplets:.1%}")
print(f"chains ending with EventLost {int(T['end EventLost']):,}, beginning with EventLost {int(T['start EventLost']):,}")
print("where chains fail:", dict(allf.most_common()))
