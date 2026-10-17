"""long_screenon_review_build.py <category folder> [...]: ScreenOn blocks made from a screen contradiction (two screen-ons
or two screen-offs in a row) that are longer than 12 h (David, 10-17: "45 ScreenOn blocks that come from a screen
contradiction are longer than 12 h, we should review them"). The 12 h only picks what to review; no rule uses it.
One item per block, with its events (long blocks trimmed), its inferred events and its longest silence.
Run screen_blocks.py and block_fails.py first. Writes <folder>/_review/long_screenon_review.json (list "longon")."""
import sys, os, glob, json
TB = os.path.expanduser("~/workspace/eyes-toolbox")
if not os.path.isdir(TB): TB = os.path.expanduser("~/mnt/eyes-toolbox")
sys.path.insert(0, TB)
import numpy as np, pandas as pd
from eyeslib.states import device_state as ds
QUIET = {"Standby Bucket Changed", "Notification Interruption", "Notification Seen"}
CTX, HEAD = 6, 60
for folder in sys.argv[1:]:
    folder = os.path.abspath(folder); out = os.path.join(folder, "_review"); items = []; done = set()
    for f in sorted({os.path.basename(g).split("_Chronicle")[0]: g for g in sorted(glob.glob(os.path.join(folder, "processed", "*_sorted_uniq_reordered.csv")))}.values()):   # the latest export per id, as the other scripts
        pid = os.path.basename(f).split("_Chronicle")[0]
        if pid in done: continue
        done.add(pid)
        bf = os.path.join(out, f"screen_blocks_{pid}.csv")
        if not os.path.exists(bf): continue
        B = pd.read_csv(bf)
        L = B[(B.block == "ScreenOn") & B.why.fillna("").astype(str).str.startswith("two") & (B.h > 12)]
        if not len(L): continue
        C = pd.read_csv(os.path.join(out, f"power_cycles_{pid}.csv"))
        inf_f = os.path.join(out, f"block_inferred_{pid}.csv")
        INF = pd.read_csv(inf_f) if os.path.exists(inf_f) else pd.DataFrame(columns=["block_i", "event", "app", "after_t", "before_t"])
        ff = os.path.join(out, f"block_fails_{pid}.csv"); F = pd.read_csv(ff) if os.path.exists(ff) else pd.DataFrame(columns=["block_i", "t", "fail"])
        tz = pd.read_csv(f, usecols=["timezone"], nrows=1).timezone.iloc[0] or "UTC"
        ev = ds.load_events(f); t = ev.t.to_numpy(); nm = ev.name.to_numpy(); pk = ev.app_package_name.astype(str).to_numpy()
        keep = np.where(~np.isin(nm, list(QUIET)))[0]
        for bi, b in L.iterrows():
            ka, kb = np.searchsorted(t[keep], b.start_t - 1e-3, "left"), np.searchsorted(t[keep], b.end_t + 1e-3, "right")
            ins = keep[ka:kb]
            tt = np.r_[b.start_t, t[ins], b.end_t]; g = np.diff(tt); j = int(g.argmax())
            fb = F[F.block_i == bi]; ft = {round(x, 3): w for x, w in zip(fb.t, fb.fail)}
            row = lambda k, role: [float(t[k]), nm[k] + (f"  [{ft[round(float(t[k]), 3)]}]" if role == "first" else ""), pk[k], role]
            rows = [row(k, "first" if nm[k].startswith("Activity") and round(float(t[k]), 3) in ft else "between") for k in ins]
            if len(rows) > 2 * HEAD:                       # keep both ends and the events around the longest silence
                gi = j - 1                                 # rows index of the event before the silence
                keepj = sorted(set(range(HEAD)) | set(range(len(rows) - HEAD, len(rows))) | set(range(max(gi - 10, 0), min(gi + 12, len(rows)))))
                cut, last = [], -1
                for jj in keepj:
                    if jj > last + 1: cut.append([None, f"... {jj - last - 1} more events ...", "", "between"])
                    cut.append(rows[jj]); last = jj
                rows = cut
            c = C.iloc[int(b.cycle)]
            items.append(dict(id=f"lo|{b.block_id}", list="longon", file=pid, folder=os.path.basename(folder), tz=tz,
                              chain=int(b.cycle), chain_start=c.start, chain_end=c.end, chain_start_by=c.start_by, chain_end_by=c.end_by,
                              chain_t0=float(c.start_t), chain_t1=float(c.end_t), chain_repeats=int(c.screen_repeats),
                              block_id=str(b.block_id), kind="ScreenOn longer than 12 h, from a screen contradiction", block="ScreenOn",
                              fail="longon", why=str(b.why), block_t0=float(b.start_t), block_t1=float(b.end_t),
                              block_start_by=str(b.start_by), block_end_by=str(b.end_by), lost="",
                              t1=float(b.start_t), t2=float(b.end_t), gap_s=round(float(b.end_t - b.start_t), 1), n_between=len(ins),
                              n_app=int(sum(nm[k].startswith("Activity") for k in ins)), n_fail=len(fb), n_kind_total=0, fails=sorted(set(fb.fail)),
                              silence_t0=float(tt[j]), silence_t1=float(tt[j + 1]), silence_h=round(float(g[j]) / 3600, 1),
                              inferred=[dict(event=r.event, app=r.app, after_t=None if pd.isna(r.after_t) else float(r.after_t), before_t=float(r.before_t))
                                        for r in INF[INF.block_i == bi].itertuples()],
                              events=[row(k, "before") for k in keep[max(ka - CTX, 0):ka]] + rows + [row(k, "after") for k in keep[kb:kb + CTX]]))
    items.sort(key=lambda i: -i["gap_s"])
    for i in items: i["n_kind_total"] = len(items)
    json.dump(dict(folder=os.path.basename(folder), items=items), open(os.path.join(out, "long_screenon_review.json"), "w"))
    print(os.path.basename(folder), len(items), "long ScreenOn blocks,", round(sum(i["gap_s"] for i in items) / 3600), "h; in their longest silence:",
          round(sum(i["silence_h"] for i in items)), "h")
