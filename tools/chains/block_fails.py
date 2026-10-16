"""block_fails.py <category folder>: app-chain failures inside each device-state block (David, 10-16: "in each Device State
Blocks, there might be App Activity Chain failure. We should review these blocks and see the cause. There might be activity
log loss, too."). Run screen_blocks.py first. Event order only.

Inside each ScreenOn / ScreenOff / EventLost block, the app events are walked with the run_until_fail rules (screen_blocks.py).
Where an event does not follow, the failure is recorded and construction restarts at that event (its start may lie before):
  resumed, previous app never Paused   R(A) .. R(B) .. R(C) with no P(A)         -> a Paused lost
  paused, app not in front             P(X) with X not Resumed in this run       -> a Resumed lost (or X in front from before)
  stopped in front, no Paused          S(X) while X in front                     -> a kill (C8) or a Paused lost
  stopped twice                        S(X) with no Paused-not-Stopped screen    -> a Paused lost, or a duplicate
  resumed in ScreenOff                 any Resumed inside a ScreenOff block      -> a screen-on lost, or an app over the lock screen
Writes <folder>/_review/block_fails_<pid>.csv (one row per failure) and block_fails.tsv (per file); prints a summary."""
import sys, os, glob, collections
TB = os.path.expanduser("~/workspace/eyes-toolbox")
if not os.path.isdir(TB): TB = os.path.expanduser("~/mnt/eyes-toolbox")
sys.path.insert(0, TB)
import numpy as np, pandas as pd
from eyeslib.states import device_state as ds
APP = {"Activity Resumed", "Activity Paused", "Activity Stopped"}
folder = os.path.abspath(sys.argv[1]); out = os.path.join(folder, "_review")

def walk(idx, nm, pk, lead=("Activity Stopped",)):
    """Construction with restarts. Returns [(index, failure kind, app in front or None)]."""
    fails = []; front = pending = None; waiting = collections.Counter(); seen = set(); seen_r = False
    for k in idx:
        e, x = nm[k], pk[k]
        if not seen_r and e in lead:
            if e == "Activity Paused": waiting[x] += 1
            seen.add(x); continue
        why = None
        if e == "Activity Resumed":
            seen_r = True
            if pending is not None: why = "resumed, previous app never Paused"; fr = pending; pending = None
            if front is not None: pending = front
            front = x
        elif e == "Activity Paused":
            if x == pending: pending = None; waiting[x] += 1
            elif x == front: front = None; waiting[x] += 1
            else: why = "paused, app not in front"; fr = front; waiting[x] += 1
        else:
            if waiting[x] > 0: waiting[x] -= 1
            elif x not in seen: pass
            elif x == front or x == pending:
                why = "stopped in front, no Paused"; fr = x
                if x == front: front = None
                else: pending = None
            else: why = "stopped twice"; fr = None
        seen.add(x)
        if why: fails.append((k, why, fr))
    return fails

rows = []; per = []
for f in sorted(glob.glob(os.path.join(folder, "processed", "*_sorted_uniq_reordered.csv"))):
    pid = os.path.basename(f).split("_Chronicle")[0]; bf = os.path.join(out, f"screen_blocks_{pid}.csv")
    if not os.path.exists(bf): continue
    ev = ds.load_events(f); t = ev.t.to_numpy(); nm = ev.name.to_numpy(); pk = ev.app_package_name.astype(str).to_numpy()
    app = np.where(np.isin(nm, list(APP)))[0]
    B = pd.read_csv(bf); R = []
    for bi, b in B.iterrows():
        lo, hi = np.searchsorted(t[app], b.start_t + 1e-3, "right"), np.searchsorted(t[app], b.end_t - 1e-3, "left")
        idx = app[lo:hi]
        if not len(idx): continue
        if b.block == "ScreenOff":
            for k in idx:
                if nm[k] == "Activity Resumed": R.append(dict(block_i=bi, cycle=b.cycle, block=b.block, t=t[k], event=nm[k], app=pk[k], fail="resumed in ScreenOff", front=""))
            continue
        lead = ("Activity Paused", "Activity Stopped") if b.block == "EventLost" or b.start_by == "EventLost" else ("Activity Stopped",)
        for k, why, fr in walk(idx, nm, pk, lead):
            R.append(dict(block_i=bi, cycle=b.cycle, block=b.block, t=t[k], event=nm[k], app=pk[k], fail=why, front=fr or ""))
    R = pd.DataFrame(R, columns=["block_i", "cycle", "block", "t", "event", "app", "fail", "front"])
    R.to_csv(os.path.join(out, f"block_fails_{pid}.csv"), index=False)
    nb = B.groupby("block").size()
    fb = R.groupby("block").block_i.nunique() if len(R) else pd.Series(dtype=int)
    per.append(dict(pid=pid, blocks=len(B), **{f"{k}_blocks": int(nb.get(k, 0)) for k in ["ScreenOn", "ScreenOff", "EventLost"]},
                    **{f"{k}_failing": int(fb.get(k, 0)) for k in ["ScreenOn", "ScreenOff", "EventLost"]}, failures=len(R)))
    rows.append(R.assign(pid=pid))
P = pd.DataFrame(per); P.to_csv(os.path.join(out, "block_fails.tsv"), sep="\t", index=False)
A = pd.concat(rows)
T = P.sum(numeric_only=True)
for k in ["ScreenOn", "ScreenOff", "EventLost"]:
    print(f"{k}: {int(T[k + '_blocks']):,} blocks, with an app-chain failure {int(T[k + '_failing']):,} ({100 * T[k + '_failing'] / max(T[k + '_blocks'], 1):.1f}%)")
print("failures by kind and block:"); print(A.groupby(["block", "fail"]).size().unstack(0).fillna(0).astype(int).to_string())
print("files by share of failing blocks (top):"); P["fail_%"] = (100 * (P.ScreenOn_failing + P.ScreenOff_failing + P.EventLost_failing) / P.blocks).round(1)
print(P.sort_values("fail_%", ascending=False)[["pid", "blocks", "ScreenOn_failing", "ScreenOff_failing", "EventLost_failing", "failures", "fail_%"]].head(8).to_string(index=False))
