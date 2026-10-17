"""block_review_build.py <category folder> [...]: review list of app-chain failures inside device-state blocks (David, 10-16:
"in each Device State Blocks, there might be App Activity Chain failure. We should review these blocks and see the cause.
There might be activity log loss, too."). Run block_fails.py first.
One item per (block, failure kind). Sampled: up to PER items for each block type x failure kind, spread round-robin over
files, so every kind and many files are seen; counts of all failures are kept in the item (n_kind_total).
Writes <folder>/_review/block_review.json, read by the review app's "Power cycles" tab (list "App-chain failures in blocks")."""
import sys, os, glob, json, collections
TB = os.path.expanduser("~/workspace/eyes-toolbox")
if not os.path.isdir(TB): TB = os.path.expanduser("~/mnt/eyes-toolbox")
sys.path.insert(0, TB)
import numpy as np, pandas as pd
from eyeslib.states import device_state as ds
QUIET = {"Standby Bucket Changed", "Notification Interruption", "Notification Seen"}
PER, CTX, MAXMID = 12, 6, 80
for folder in sys.argv[1:]:
    folder = os.path.abspath(folder); out = os.path.join(folder, "_review")
    F = []
    for f in glob.glob(os.path.join(out, "block_fails_*.csv")):
        d = pd.read_csv(f)
        if len(d): F.append(d.assign(pid=os.path.basename(f)[len("block_fails_"):-4]))
    F = pd.concat(F, ignore_index=True)
    G = F.groupby(["block", "fail", "pid", "block_i"]).agg(t=("t", "min"), n=("t", "size")).reset_index()
    tot = F.groupby(["block", "fail"]).size().to_dict()
    pick = []
    for (blk, fail), g in G.groupby(["block", "fail"]):
        byf = [list(x.itertuples()) for _, x in g.sample(frac=1, random_state=1).groupby("pid")]
        got = []
        for r in range(max(len(l) for l in byf)):           # round-robin over files
            for lst in byf:
                if r < len(lst) and len(got) < PER: got.append(lst[r])
            if len(got) >= PER: break
        pick += got
    items = []
    for pid, sel in collections.defaultdict(list, {k: [p for p in pick if p.pid == k] for k in {p.pid for p in pick}}).items():
        f = glob.glob(os.path.join(folder, "processed", f"{pid}_Chronicle*_sorted_uniq_reordered.csv"))[0]
        tz = pd.read_csv(f, usecols=["timezone"], nrows=1).timezone.iloc[0] or "UTC"
        ev = ds.load_events(f); t = ev.t.to_numpy(); nm = ev.name.to_numpy(); pk = ev.app_package_name.astype(str).to_numpy()
        keep = np.where(~np.isin(nm, list(QUIET)))[0]
        B = pd.read_csv(os.path.join(out, f"screen_blocks_{pid}.csv")); C = pd.read_csv(os.path.join(out, f"power_cycles_{pid}.csv"))
        Fp = F[F.pid == pid]
        for p in sel:
            b = B.iloc[p.block_i]; c = C.iloc[int(b.cycle)]
            ft = set(np.round(Fp[(Fp.block_i == p.block_i) & (Fp.fail == p.fail)].t.to_numpy(), 3))
            ka, kb = np.searchsorted(t[keep], b.start_t - 1e-3, "left"), np.searchsorted(t[keep], b.end_t + 1e-3, "right")
            row = lambda k, role: [float(t[k]), nm[k], pk[k], role]
            inside = [row(k, "first" if round(float(t[k]), 3) in ft and nm[k].startswith("Activity") else "between") for k in keep[ka:kb]]
            if len(inside) > MAXMID:                    # keep the failures and their neighbours
                fi = [j for j, r in enumerate(inside) if r[3] == "first"]
                keepj = sorted({j for x in fi[:10] for j in range(max(x - 4, 0), min(x + 5, len(inside)))} | {0, len(inside) - 1})
                cut, last = [], -1
                for j in keepj:
                    if j > last + 1: cut.append([None, f"... {j - last - 1} more events ...", "", "between"])
                    cut.append(inside[j]); last = j
                inside = cut
            evs = [row(k, "before") for k in keep[max(ka - CTX, 0):ka]] + inside + [row(k, "after") for k in keep[kb:kb + CTX]]
            items.append(dict(id=f"blk|{b.block_id}|{p.fail}", list="block", file=pid, folder=os.path.basename(folder), tz=tz,
                              chain=int(b.cycle), chain_start=c.start, chain_end=c.end, chain_start_by=c.start_by, chain_end_by=c.end_by,
                              chain_t0=float(c.start_t), chain_t1=float(c.end_t), chain_repeats=int(c.screen_repeats),
                              block_id=str(b.block_id) if "block_id" in b else "", kind=f"{b.block}: {p.fail}", block=b.block, fail=p.fail, block_t0=float(b.start_t), block_t1=float(b.end_t),
                              block_start_by=str(b.start_by), block_end_by=str(b.end_by), lost=str(b.get("lost", "")) if isinstance(b.get("lost", ""), str) else "",
                              t1=float(p.t), t2=float(b.end_t), gap_s=round(float(b.end_t - b.start_t), 1), n_between=int(kb - ka),
                              n_fail=int(p.n), n_kind_total=int(tot[(p.block, p.fail)]), events=evs))
    items.sort(key=lambda i: (i["block"], i["fail"], i["file"], i["t1"]))
    json.dump(dict(folder=os.path.basename(folder), items=items, totals={f"{k[0]}: {k[1]}": int(v) for k, v in tot.items()}),
              open(os.path.join(out, "block_review.json"), "w"))
    print(os.path.basename(folder), len(items), "items;", collections.Counter(i["kind"] for i in items))
