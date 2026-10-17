"""eventlost_review_build.py <category folder> [...]: every EventLost block that has app events inside (David, 10-16: "I
thought EventLost block should be empty ... i want to review the ... EventLost blocks"). One item per block: first the blocks
where the app chain fails inside (block_fails.py), then those whose app events form consistent chains. Run block_fails.py
first. Writes <folder>/_review/eventlost_review.json (review app, Power cycles tab, list "EventLost blocks with app events")."""
import sys, os, glob, json
TB = os.path.expanduser("~/workspace/eyes-toolbox")
if not os.path.isdir(TB): TB = os.path.expanduser("~/mnt/eyes-toolbox")
sys.path.insert(0, TB)
import numpy as np, pandas as pd
from eyeslib.states import device_state as ds
QUIET = {"Standby Bucket Changed", "Notification Interruption", "Notification Seen"}
APP = {"Activity Resumed", "Activity Paused", "Activity Stopped"}
CTX, MAXMID = 6, 120
for folder in sys.argv[1:]:
    folder = os.path.abspath(folder); out = os.path.join(folder, "_review"); items = []
    for f in sorted(glob.glob(os.path.join(folder, "processed", "*_sorted_uniq_reordered.csv"))):
        pid = os.path.basename(f).split("_Chronicle")[0]
        bf, ff = os.path.join(out, f"screen_blocks_{pid}.csv"), os.path.join(out, f"block_fails_{pid}.csv")
        if not (os.path.exists(bf) and os.path.exists(ff)): continue
        B = pd.read_csv(bf); L = B[B.block == "EventLost"]
        if not len(L): continue
        F = pd.read_csv(ff); C = pd.read_csv(os.path.join(out, f"power_cycles_{pid}.csv"))
        inf_f = os.path.join(out, f"block_inferred_{pid}.csv")
        INF = pd.read_csv(inf_f) if os.path.exists(inf_f) else pd.DataFrame(columns=["block_i", "event", "app", "after_t", "before_t"])
        AMB = {"stopped in front, no Paused", "stopped twice"}
        tz = pd.read_csv(f, usecols=["timezone"], nrows=1).timezone.iloc[0] or "UTC"
        ev = ds.load_events(f); t = ev.t.to_numpy(); nm = ev.name.to_numpy(); pk = ev.app_package_name.astype(str).to_numpy()
        keep = np.where(~np.isin(nm, list(QUIET)))[0]
        for bi, b in L.iterrows():
            ka, kb = np.searchsorted(t[keep], b.start_t - 1e-3, "left"), np.searchsorted(t[keep], b.end_t + 1e-3, "right")
            ins = keep[ka:kb]; inner = [k for k in ins if nm[k] in APP and b.start_t + 1e-3 < t[k] < b.end_t - 1e-3]
            if not inner: continue
            fb = F[F.block_i == bi]; ft = {round(x, 3): w for x, w in zip(fb.t, fb.fail)}
            row = lambda k, role: [float(t[k]), nm[k] + (f"  [{ft[round(float(t[k]), 3)]}]" if role == "first" else ""), pk[k], role]
            rows = [row(k, "first" if nm[k] in APP and round(float(t[k]), 3) in ft else "between") for k in ins]
            if len(rows) > MAXMID: rows = rows[:MAXMID // 2] + [[None, f"... {len(rows) - MAXMID} more events ...", "", "between"]] + rows[-MAXMID // 2:]
            c = C.iloc[int(b.cycle)]
            items.append(dict(id=f"el|{b.block_id}", list="eventlost", file=pid, folder=os.path.basename(folder), tz=tz,
                              chain=int(b.cycle), chain_start=c.start, chain_end=c.end, chain_start_by=c.start_by, chain_end_by=c.end_by,
                              chain_t0=float(c.start_t), chain_t1=float(c.end_t), chain_repeats=int(c.screen_repeats),
                              block_id=str(b.block_id) if "block_id" in b else "", kind=("Inconsistent EventLost block (two readings fit)" if fb.fail.isin(AMB).any() else
                                    "EventLost block, consistent with inferred events" if len(fb) else "Consistent app events inside an EventLost block"),
                              inferred=[dict(event=r.event, app=r.app, after_t=None if pd.isna(r.after_t) else float(r.after_t), before_t=float(r.before_t))
                                        for r in INF[INF.block_i == bi].itertuples()],
                              block="EventLost", fail="eventlost-fail" if fb.fail.isin(AMB).any() else ("eventlost-inferred" if len(fb) else "eventlost-ok"), why=str(b.why),
                              block_t0=float(b.start_t), block_t1=float(b.end_t), block_start_by=str(b.start_by), block_end_by=str(b.end_by),
                              lost=b.lost if isinstance(b.lost, str) else "", t1=float(t[inner[0]]), t2=float(b.end_t),
                              gap_s=round(float(b.end_t - b.start_t), 1), n_between=len(ins), n_app=len(inner),
                              n_fail=len(fb), n_kind_total=0, fails=sorted(set(fb.fail)),
                              events=[row(k, "before") for k in keep[max(ka - CTX, 0):ka]] + rows + [row(k, "after") for k in keep[kb:kb + CTX]]))
    items.sort(key=lambda i: (["eventlost-fail", "eventlost-inferred", "eventlost-ok"].index(i["fail"]), i["file"], i["t1"]))
    for k in ("eventlost-fail", "eventlost-inferred", "eventlost-ok"):
        n = sum(i["fail"] == k for i in items)
        for i in items:
            if i["fail"] == k: i["n_kind_total"] = n
    json.dump(dict(folder=os.path.basename(folder), items=items), open(os.path.join(out, "eventlost_review.json"), "w"))
    c = {k: sum(i["fail"] == k for i in items) for k in ("eventlost-fail", "eventlost-inferred", "eventlost-ok")}
    print(os.path.basename(folder), len(items), "EventLost blocks with app events:", c["eventlost-fail"], "Inconsistent,", c["eventlost-inferred"],
          "consistent with inferred events,", c["eventlost-ok"], "consistent")
