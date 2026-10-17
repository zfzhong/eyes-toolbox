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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chain_core
from eyeslib.states import device_state as ds
APP = {"Activity Resumed", "Activity Paused", "Activity Stopped"}
folder = os.path.abspath(sys.argv[1]); out = os.path.join(folder, "_review")

def walk(idx, nm, pk, lead=("Activity Stopped",), inferred=None):
    """Construction with restarts: all failures [(index, kind, app)], from the FIFO triplet queue of chain_core.py;
    inferred events (Paused(infer) / Resumed(infer)) go to the list inferred."""
    return chain_core.walk(idx, nm, pk, lead, inferred=inferred)[1]

rows = []; per = []
for f in sorted(glob.glob(os.path.join(folder, "processed", "*_sorted_uniq_reordered.csv"))):
    pid = os.path.basename(f).split("_Chronicle")[0]; bf = os.path.join(out, f"screen_blocks_{pid}.csv")
    if not os.path.exists(bf): continue
    ev = ds.load_events(f); t = ev.t.to_numpy(); nm = ev.name.to_numpy(); pk = ev.app_package_name.astype(str).to_numpy()
    app = np.where(np.isin(nm, list(APP)))[0]
    B = pd.read_csv(bf); R = []; I = []
    for bi, b in B.iterrows():
        lo, hi = np.searchsorted(t[app], b.start_t + 1e-3, "right"), np.searchsorted(t[app], b.end_t - 1e-3, "left")
        idx = app[lo:hi]
        if not len(idx): continue
        if b.block == "ScreenOff":
            for k in idx:
                if nm[k] == "Activity Resumed": R.append(dict(block_i=bi, cycle=b.cycle, block=b.block, t=t[k], event=nm[k], app=pk[k], fail="resumed in ScreenOff", front=""))
            continue
        lead = ("Activity Paused", "Activity Stopped") if b.block == "EventLost" or b.start_by == "EventLost" else ("Activity Stopped",)
        inf = []
        for k, why, fr in walk(idx, nm, pk, lead, inf):
            R.append(dict(block_i=bi, cycle=b.cycle, block=b.block, t=t[k], event=nm[k], app=pk[k], fail=why, front=fr or ""))
        for ka, kb, ev, ia in inf:
            I.append(dict(block_i=bi, block_id=b.get("block_id", ""), event=ev.replace("Activity ", "") + "(infer)", app=ia,
                          after_t=t[ka] if ka is not None else np.nan, before_t=t[kb]))
    R = pd.DataFrame(R, columns=["block_i", "cycle", "block", "t", "event", "app", "fail", "front"])
    R.to_csv(os.path.join(out, f"block_fails_{pid}.csv"), index=False)
    pd.DataFrame(I, columns=["block_i", "block_id", "event", "app", "after_t", "before_t"]).to_csv(os.path.join(out, f"block_inferred_{pid}.csv"), index=False)
    n_inf = len(I)
    nb = B.groupby("block").size()
    fb = R.groupby("block").block_i.nunique() if len(R) else pd.Series(dtype=int)
    per.append(dict(pid=pid, blocks=len(B), **{f"{k}_blocks": int(nb.get(k, 0)) for k in ["ScreenOn", "ScreenOff", "EventLost"]},
                    **{f"{k}_failing": int(fb.get(k, 0)) for k in ["ScreenOn", "ScreenOff", "EventLost"]}, failures=len(R),
                    inferred=n_inf, ambiguous=int(R.fail.isin([chain_core.FAIL_KILL, chain_core.FAIL_STRAY]).sum()) if len(R) else 0))
    rows.append(R.assign(pid=pid))
P = pd.DataFrame(per); P.to_csv(os.path.join(out, "block_fails.tsv"), sep="\t", index=False)
A = pd.concat(rows)
T = P.sum(numeric_only=True)
for k in ["ScreenOn", "ScreenOff", "EventLost"]:
    print(f"{k}: {int(T[k + '_blocks']):,} blocks, with an app-chain failure {int(T[k + '_failing']):,} ({100 * T[k + '_failing'] / max(T[k + '_blocks'], 1):.1f}%)")
print(f"inferred events: {int(T['inferred']):,} (Paused(infer) / Resumed(infer)); ambiguous failures (kill or lost Paused, stray Stopped): {int(T['ambiguous']):,}")
print("failures by kind and block:"); print(A.groupby(["block", "fail"]).size().unstack(0).fillna(0).astype(int).to_string())
print("files by share of failing blocks (top):"); P["fail_%"] = (100 * (P.ScreenOn_failing + P.ScreenOff_failing + P.EventLost_failing) / P.blocks).round(1)
print(P.sort_values("fail_%", ascending=False)[["pid", "blocks", "ScreenOn_failing", "ScreenOff_failing", "EventLost_failing", "failures", "fail_%"]].head(8).to_string(index=False))
