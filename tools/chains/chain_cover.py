"""chain_cover.py <category folder>: how much of each file's logged time the app chain explains.
Every moment from the first to the last event is put in one class (first match wins):
  app            inside a resumed -> paused block whose Resumed and Paused are both real (act_one), screen on
  screen off     between Screen Non-interactive and the next Screen Interactive (or a shutdown -> boot)
  locked         screen on, lock screen up (Keyguard Shown, no Keyguard Hidden yet), no app block
  silence        no event at all for 30 min or more (screen state unknown: lost screen-off, logger stopped, device off)
  gap            screen on and unlocked, but no real app block: the chain is broken here
Prints one line per file and writes <folder>/_review/chain_cover.tsv."""
import sys, os, glob
TB = os.path.expanduser("~/workspace/eyes-toolbox")
if not os.path.isdir(TB): TB = os.path.expanduser("~/mnt/eyes-toolbox")
sys.path.insert(0, TB)
import numpy as np, pandas as pd
from eyeslib.states import device_state as ds
folder = os.path.abspath(sys.argv[1]); P = os.path.join(folder, "processed")
REAL_R = {"Activity Resumed", "Move to Foreground"}; REAL_P = {"Activity Paused", "Move to Background", "MatchingPreviousBlock", "MatchingCurrentBlock"}
rows = []
for f in sorted(glob.glob(os.path.join(P, "*_sorted_uniq_reordered.csv"))):
    stem = os.path.basename(f)[:-len("_sorted_uniq_reordered.csv")]; pid = stem.split("_Chronicle")[0]
    ev = ds.load_events(f); t = ev.t.to_numpy(); nm = ev.name.to_numpy()
    t0, t1 = t[0], t[-1]
    grid = np.arange(t0, t1, 1.0)                      # one-second grid
    cls = np.full(len(grid), 3, np.int8)               # 3 gap, 2 locked, 1 screen off, 0 app
    # screen state and lock state by forward fill over the grid
    scr = np.full(len(grid), 1, np.int8); lock = np.zeros(len(grid), np.int8)
    st = [(x, 1) for x, n in zip(t, nm) if n == "Screen Interactive"] + [(x, 0) for x, n in zip(t, nm) if n in ("Screen Non-interactive", "Device Shutdown")]
    kg = [(x, 1) for x, n in zip(t, nm) if n == "Keyguard Shown"] + [(x, 0) for x, n in zip(t, nm) if n == "Keyguard Hidden"]
    def ffill(changes, default):
        out = np.full(len(grid), default, np.int8)
        if not changes: return out
        changes.sort(); ct = np.array([c[0] for c in changes]); cv = np.array([c[1] for c in changes], np.int8)
        k = np.searchsorted(ct, grid, "right") - 1
        out[k >= 0] = cv[k[k >= 0]]
        return out
    scr = ffill(st, 1); lock = ffill(kg, 0)
    cls[(scr == 1) & (lock == 1)] = 2
    cls[scr == 0] = 1
    a = pd.read_csv(os.path.join(P, stem + "_sorted_uniq_reordered_act_one.csv"))
    a = a[a.resume_event.isin(REAL_R) & a.pause_event.isin(REAL_P)]
    rs = pd.to_datetime(a.resume_time, utc=True, format="ISO8601").astype("int64").to_numpy() / 1e9
    ps = pd.to_datetime(a.pause_time, utc=True, format="ISO8601").astype("int64").to_numpy() / 1e9
    app = np.zeros(len(grid), bool)
    for r, p in zip(rs, ps):
        i0, i1 = np.searchsorted(grid, r), np.searchsorted(grid, p)
        app[i0:i1] = True
    # silences: inside an interval of 30 min or more with no event at all
    d = np.diff(t); big = np.where(d >= 1800)[0]
    for k in big:
        i0, i1 = np.searchsorted(grid, t[k]), np.searchsorted(grid, t[k + 1])
        sel = slice(i0, i1); cls[sel] = np.where(cls[sel] == 1, 1, 4)    # screen known off stays off
    cls[app & (scr == 1)] = 0
    n = np.bincount(cls, minlength=5) / 3600
    tot = n.sum()
    on = n[0] + n[3]
    rows.append((pid, round((t1 - t0) / 86400, 1), *[round(x, 1) for x in n], round(100 * n[0] / on, 2) if on else 100.0))
    print(f"{pid:20s} days {rows[-1][1]:5.1f}  app {n[0]:7.1f} h  gap {n[3]:6.1f} h  -> chain covers {rows[-1][-1]:6.2f}% of unlocked screen-on time | screen off {n[1]:7.1f} h  locked {n[2]:5.1f} h  silence {n[4]:6.1f} h", flush=True)
pd.DataFrame(rows, columns=["pid", "days", "app_h", "screen_off_h", "locked_h", "gap_h", "silence_h", "chain_cover_pct"]).to_csv(os.path.join(folder, "_review", "chain_cover.tsv"), sep="\t", index=False)
