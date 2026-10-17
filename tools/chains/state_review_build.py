"""state_review_build.py <category folder> [...] (Power Cycles): review list for the contradictory parts of each Power Cycle (David, 10-16):
two screen-on (or two screen-off) events in a row inside a Power Cycle. One item per contradiction, with the chain's start /
end (Bootup / LogStart, Shutdown / LogEnd), the events before the first screen event, every event between the two, and the
events after the second. Writes <folder>/_review/state_review.json, read by the review app's "State chains" tab.
Run power_cycles.py on the folder first."""
import sys, os, glob, json
TB = os.path.expanduser("~/workspace/eyes-toolbox")
if not os.path.isdir(TB): TB = os.path.expanduser("~/mnt/eyes-toolbox")
sys.path.insert(0, TB)
import numpy as np, pandas as pd
from eyeslib.states import device_state as ds
ON, OFF = "Screen Interactive", "Screen Non-interactive"
QUIET = {"Standby Bucket Changed", "Notification Interruption", "Notification Seen"}
CTX, MAXMID = 8, 80
for folder in sys.argv[1:]:
    folder = os.path.abspath(folder); out = os.path.join(folder, "_review"); items = []
    for f in sorted(glob.glob(os.path.join(folder, "processed", "*_sorted_uniq_reordered.csv"))):
        stem = os.path.basename(f)[:-len("_sorted_uniq_reordered.csv")]; pid = stem.split("_Chronicle")[0]
        cf = os.path.join(out, f"power_cycles_{pid}.csv")
        if not os.path.exists(cf): continue
        C = pd.read_csv(cf)
        bf = os.path.join(out, f"screen_blocks_{pid}.csv")
        SB = pd.read_csv(bf) if os.path.exists(bf) else None
        tz = pd.read_csv(f, usecols=["timezone"], nrows=1).timezone.iloc[0] or "UTC"
        ev = ds.load_events(f); t = ev.t.to_numpy(); nm = ev.name.to_numpy(); pk = ev.app_package_name.astype(str).to_numpy()
        keep = np.where(~np.isin(nm, list(QUIET)))[0]
        def row(k, role):
            return [float(t[k]), nm[k], pk[k], role]
        for ci, c in C[C.screen_repeats > 0].iterrows():
            i0, i1 = np.searchsorted(t, c.start_t, "left"), np.searchsorted(t, c.end_t, "right")
            sc = [i for i in keep[(keep >= i0) & (keep < i1)] if nm[i] in (ON, OFF)]
            for a, b in zip(sc, sc[1:]):
                if nm[a] != nm[b]: continue
                ka, kb = np.searchsorted(keep, a), np.searchsorted(keep, b)
                before = [row(k, "before") for k in keep[max(ka - CTX, 0):ka]]
                mid = [row(k, "between") for k in keep[ka + 1:kb]]
                after = [row(k, "after") for k in keep[kb + 1:kb + 1 + CTX]]
                more = max(len(mid) - MAXMID, 0)
                if more: mid = mid[:MAXMID // 2] + [[None, f"... {more} more events ...", "", "between"]] + mid[-MAXMID // 2:]
                items.append(dict(id=f"{pid}|{float(t[a]):.3f}|{'on' if nm[a] == ON else 'off'}", file=pid, folder=os.path.basename(folder), tz=tz,
                                  chain=int(ci), chain_start=c.start, chain_end=c.end, chain_start_by=c.start_by, chain_end_by=c.end_by,
                                  chain_t0=float(c.start_t), chain_t1=float(c.end_t), chain_repeats=int(c.screen_repeats),
                                  kind="two screen-ons" if nm[a] == ON else "two screen-offs",
                                  t1=float(t[a]), t2=float(t[b]), gap_s=round(float(t[b] - t[a]), 1), n_between=len(keep[ka + 1:kb]),
                                  events=before + [row(a, "first")] + mid + [row(b, "second")] + after,
                                  blocks=[] if SB is None or "block_id" not in SB else
                                  [dict(id=r.block_id, block=r.block, t0=float(r.start_t), t1=float(r.end_t), start_by=str(r.start_by),
                                        end_by=str(r.end_by), lost=r.lost if isinstance(r.lost, str) else "")
                                   for r in SB[(SB.end_t >= t[a] - 1e-3) & (SB.start_t <= t[b] + 1e-3)].itertuples()]))
    json.dump(dict(folder=os.path.basename(folder), items=items), open(os.path.join(out, "state_review.json"), "w"))
    print(os.path.basename(folder), len(items), "items in", len({(i["file"], i["chain"]) for i in items}), "Power Cycles,", len({i["file"] for i in items}), "files")
