"""resolve_unknown.py <category folder>: use the app activity inside each Lost block (formerly "Unknown") to tell what was lost (David, 10-16:
"To identify the Unknown block, we need activity level events to help"). Event order only. Run screen_blocks.py first.
Inside a Lost block, the app triplet chains (chain_logic rules) are built from the block's app events:
  an app chain (Resumed ... Paused)                       an app in front: the screen was on            -> ScreenOn
  a chain that ends properly (last app Paused + Stopped,  what Android logs at a screen-off: the lost
    nothing Resumed after it)                             screen-off is there, the screen is off until  -> ScreenOff
                                                          the next chain starts (the lost screen-on)
  a boot signature (Settings Paused, no Resumed:          a power cycle was lost there                  -> PowerLost
    FallbackHome, pattern A1)
  a chain that fails (no proper end, a Paused of an app   the stretch stays                             -> Lost
    not in front ...)
The block's own bounding events: two Screen Interactive -> it starts on; two Screen Non-interactive -> it starts off.
Writes <folder>/_review/unknown_resolved.csv (one row per part) and prints how much of the Lost time is explained."""
import sys, os, glob, importlib.util
TB = os.path.expanduser("~/workspace/eyes-toolbox")
if not os.path.isdir(TB): TB = os.path.expanduser("~/mnt/eyes-toolbox")
sys.path.insert(0, TB)
import numpy as np, pandas as pd
from eyeslib.states import device_state as ds
folder = os.path.abspath(sys.argv[1]); out = os.path.join(folder, "_review")
APP = ["Activity Resumed", "Activity Paused", "Activity Stopped"]
SETTINGS = "com.android.settings"

def chains_in(t, nm, pk):
    """Triplet chains from the order of app events (chain_logic rules, without screen events). Returns chains with
    start (real Resumed), end (real Paused + Stopped, nothing Resumed after), t0, t1, boot (a Settings Paused with no Resumed)."""
    chains = []; cur = None; front = None; pending = None; waiting = {}
    def close(ok):
        nonlocal cur
        if cur is not None:
            cur["end"] = ok and cur["last_p"] is not None and cur["last_s"]; chains.append(cur)
        cur = None
    for i in range(len(t)):
        e, x = nm[i], pk[i]
        if e == "Activity Resumed":
            if pending is not None:                      # previous app never Paused: the chain fails here
                close(False); pending = None
                cur = dict(start=True, t0=t[i], t1=t[i], n=1, last_p=None, last_s=False, boot=False)   # the app in front goes on
            if front is not None:
                pending = front; cur["n"] += 1
            elif cur is not None and cur["last_p"] is not None and not cur["last_s"]:
                cur["n"] += 1
            else:
                close(True); cur = dict(start=True, t0=t[i], t1=t[i], n=1, last_p=None, last_s=False, boot=False)
            front = x; cur["last_p"] = None; cur["last_s"] = False; cur["t1"] = t[i]
        elif e == "Activity Paused":
            if pending == x: pending = None; waiting.setdefault(x, 0); waiting[x] += 1
            elif front == x:
                front = None; waiting.setdefault(x, 0); waiting[x] += 1
                if cur is not None: cur["last_p"] = t[i]; cur["t1"] = t[i]
            else:                                        # Paused of an app not in front
                close(False)
                cur = dict(start=False, t0=t[i], t1=t[i], n=1, last_p=t[i], last_s=False, boot=(x == SETTINGS))
                waiting.setdefault(x, 0); waiting[x] += 1; front = None; pending = None
        elif e == "Activity Stopped":
            if waiting.get(x, 0) > 0:
                waiting[x] -= 1
                if cur is not None and front is None and pending is None: cur["last_s"] = True; cur["t1"] = max(cur["t1"], t[i])
            elif front == x or pending == x:             # Stopped in front with no Paused
                close(False); front = None; pending = None
    close(True)
    return chains

rows = []
for f in sorted(glob.glob(os.path.join(folder, "processed", "*_sorted_uniq_reordered.csv"))):
    pid = os.path.basename(f).split("_Chronicle")[0]
    bf = os.path.join(out, f"screen_blocks_{pid}.csv")
    if not os.path.exists(bf): continue
    U = pd.read_csv(bf); U = U[(U.block == "Lost") & U.why.fillna("").astype(str).str.startswith("two")]
    if U.empty: continue
    ev = ds.load_events(f); t = ev.t.to_numpy(); nm = ev.name.to_numpy(); pk = ev.app_package_name.astype(str).to_numpy()
    for bi, b in U.iterrows():
        i0, i1 = np.searchsorted(t, b.start_t - 1e-3), np.searchsorted(t, b.end_t + 1e-3, "right")
        m = np.isin(nm[i0:i1], APP)
        ch = chains_in(t[i0:i1][m], nm[i0:i1][m], pk[i0:i1][m])
        parts = []; pos = b.start_t; state = "ScreenOn" if b.start_by == "Screen Interactive" else "ScreenOff"; known = True
        for c in ch:
            if c["boot"]:
                parts.append(("PowerLost" if known else "Lost", pos, c["t0"])); pos = c["t0"]; state = "ScreenOn"; known = True
                continue
            if c["start"]:
                # the screen was off from the previous proper end (or the block start if it starts off) to this chain's start
                parts.append((state if known else "Lost", pos, c["t0"]))
            else:
                parts.append(("Lost", pos, c["t0"]))
            parts.append(("ScreenOn", c["t0"], c["t1"]))
            pos = c["t1"]; known = c["end"]; state = "ScreenOff"
        last = "ScreenOn" if b.end_by == "Screen Non-interactive" else "ScreenOff"
        parts.append(((state if state == last or state == "ScreenOff" else "Lost") if known else "Lost", pos, b.end_t))
        for kind, a_, z_ in parts:
            if z_ > a_: rows.append(dict(file=pid, block_start=b.start_t, why=b.why, part=kind, start_t=a_, end_t=z_, h=(z_ - a_) / 3600))
R = pd.DataFrame(rows); R.to_csv(os.path.join(out, "unknown_resolved.csv"), index=False)
tot = R.groupby("part").h.sum(); T = tot.sum()
print("Lost time (contradictions) explained by app activity:", {k: f"{v:,.0f} h ({100 * v / T:.1f}%)" for k, v in tot.items()})
blk = R.groupby(["file", "block_start"]).apply(lambda g: (g.part == "Lost").sum() == 0)
print(f"Lost blocks fully explained: {int(blk.sum())} of {len(blk)}")
print("why the rest stays Lost (parts):", R[R.part == "Lost"].groupby("why").h.agg(["size", "sum"]).round(0).to_dict("index"))
