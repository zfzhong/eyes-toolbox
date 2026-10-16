"""story_cat.py <category folder> [lo hi]: app-level story checker (eyeslib.states.story) on every processed file of an
A1 category folder (kids_phone, kids_tablet, parent_phone). Writes <folder>/_review/<pid>_breaks.csv (one row per break
with the events around it) and appends one summary line per file to <folder>/_review/story_summary.tsv."""
import sys, os, glob
TB = os.path.expanduser("~/workspace/eyes-toolbox")
if not os.path.isdir(TB): TB = os.path.expanduser("~/mnt/eyes-toolbox")
sys.path.insert(0, TB)
import numpy as np, pandas as pd
from eyeslib.states import device_state as ds, profile as pf, story
folder = os.path.abspath(sys.argv[1]); out = os.path.join(folder, "_review"); os.makedirs(out, exist_ok=True)
files = sorted(glob.glob(os.path.join(folder, "processed", "*_sorted_uniq_reordered.csv")))
lo, hi = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) > 3 else (0, len(files))
for f in files[lo:hi]:
    pid = os.path.basename(f).split("_Chronicle")[0].split(" Chronicle")[0]
    ev = ds.load_events(f)
    p99, _, _ = pf.stop_delay_limits(ev)
    P = story.projections(ev)
    E, B, I = story.app_story(ev, p99, P)
    days = (ev.t.iloc[-1] - ev.t.iloc[0]) / 86400
    t, nm, pk = E.t.to_numpy(), E.name.to_numpy(), E.app_package_name.astype(str).to_numpy()
    # context: every event except notifications / standby within 15 s before and 5 s after the break (max 8 + 6)
    et, en, ep = ev.t.to_numpy(), ev.name.to_numpy(), ev.app_package_name.astype(str).to_numpy()
    keep = ~pd.Series(en).str.contains("Notification|Standby|Configuration", regex=True).to_numpy()
    kt, kn, kp = et[keep], en[keep], ep[keep]
    def context(t0):
        j = int(np.searchsorted(kt, t0))
        lo_ = max(j - 8, 0); lo_ = max(lo_, int(np.searchsorted(kt, t0 - 15)))
        hi_ = min(j + 7, int(np.searchsorted(kt, t0 + 5, "right")), len(kt))
        return " | ".join(f"{pd.to_datetime(kt[k], unit='s').strftime('%H:%M:%S.%f')[:-3]} {kn[k].replace('Activity ', '')} {kp[k]}" for k in range(lo_, hi_))
    kill = np.zeros(len(B), bool)
    for n, r in enumerate(B.itertuples()):
        if r.kind == "stop_not_paused_front":
            kill[n] = bool(((np.abs(t - t[r.i]) <= 1.0) & (nm == "Activity Resumed") & (pk != pk[r.i])).any())
    B = B.assign(kill_pattern=kill, time=pd.to_datetime(B.t, unit="s", utc=True),
                 context=[context(r.t) for r in B.itertuples()])
    B.to_csv(os.path.join(out, f"{pid}_breaks.csv"), index=False)
    k = B.kind.value_counts().to_dict()
    with open(os.path.join(out, "story_summary.tsv"), "a") as fh:
        fh.write("\t".join(map(str, [pid, round(days, 1), len(E), len(B), round(1 - len(B) / max(len(E), 1), 4),
                                     round(len(B) / max(days, .1), 1), int(kill.sum()), k])) + "\n")
    print(pid, round(days, 1), len(E), len(B), flush=True)
