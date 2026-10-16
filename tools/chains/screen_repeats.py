"""screen_repeats.py <category folder>: one row per contradiction inside a state chain - two screen-on (or two screen-off)
events in a row - with every event between them, for human review. Writes <folder>/_review/screen_repeats.csv."""
import sys, os, glob
TB = os.path.expanduser("~/workspace/eyes-toolbox")
if not os.path.isdir(TB): TB = os.path.expanduser("~/mnt/eyes-toolbox")
sys.path.insert(0, TB)
import numpy as np, pandas as pd
from eyeslib.states import device_state as ds
folder = os.path.abspath(sys.argv[1]); out = os.path.join(folder, "_review")
ON, OFF = "Screen Interactive", "Screen Non-interactive"
QUIET = {"Standby Bucket Changed", "Notification Interruption", "Notification Seen", "Configuration Change"}
rows = []
for f in sorted(glob.glob(os.path.join(folder, "processed", "*_sorted_uniq_reordered.csv"))):
    pid = os.path.basename(f).split("_Chronicle")[0]
    C = pd.read_csv(os.path.join(out, f"device_chains2_{pid}.csv"))
    ev = ds.load_events(f); t = ev.t.to_numpy(); nm = ev.name.to_numpy(); pk = ev.app_package_name.astype(str).to_numpy()
    tz = ev.attrs.get("tz", "UTC") if hasattr(ev, "attrs") else "UTC"
    for ci, c in C[C.screen_repeats > 0].iterrows():
        i0, i1 = np.searchsorted(t, c.start_t, "left"), np.searchsorted(t, c.end_t, "right")
        sc = [i for i in range(i0, i1) if nm[i] in (ON, OFF)]
        for a, b in zip(sc, sc[1:]):
            if nm[a] != nm[b]: continue
            mid = [k for k in range(a + 1, b) if nm[k] not in QUIET]
            rows.append(dict(file=pid, chain=ci, chain_start=c.start, chain_end=c.end, kind="on-on" if nm[a] == ON else "off-off",
                             first_utc=pd.to_datetime(t[a], unit="s"), second_utc=pd.to_datetime(t[b], unit="s"), gap_min=round((t[b] - t[a]) / 60, 1),
                             events_between=len(mid),
                             between=" | ".join(f"{pd.to_datetime(t[k], unit='s').strftime('%m-%d %H:%M:%S')} {nm[k].replace('Activity ', '')} {pk[k].replace('com.', '')}" for k in mid[:12]) + (" | ..." if len(mid) > 12 else "")))
R = pd.DataFrame(rows); R.to_csv(os.path.join(out, "screen_repeats.csv"), index=False)
print(len(R), "contradictions in", R.groupby("file").chain.nunique().sum(), "chains;", R.kind.value_counts().to_dict())
print("gap between the two screen events (min): median %.1f, 10%% %.1f, 90%% %.1f" % tuple(np.percentile(R.gap_min, [50, 10, 90])))
print("events between: none", int((R.events_between == 0).sum()), "| 1-5", int(R.events_between.between(1, 5).sum()), "| more", int((R.events_between > 5).sum()))
