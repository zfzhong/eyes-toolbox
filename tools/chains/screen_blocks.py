"""screen_blocks.py <category folder>: inside each Power Cycle, the alternation of ScreenOn and ScreenOff blocks (David, 10-16),
event order only, no thresholds. Run power_cycles.py first.
Events (Chronicle's names) vs blocks (periods): a ScreenOn block runs from a Screen Interactive event to the next Screen
Non-interactive event; a ScreenOff block the reverse.
Unknown blocks: where the log contradicts itself nothing is placed (David, 10-16: "In theory, we dont know what happened
between two ScreenOn events. We are sure: some events got lost. They might be screen off, they might be shutdown and then
bootup."):
  two Screen Interactive in a row      Unknown from the first to the second (screen-off lost, or shutdown + boot lost)
  two Screen Non-interactive in a row  Unknown from the first to the second (screen-on lost, or boot + shutdown lost)
  before the first screen event        after Bootup: ScreenOn if that event is a Screen Non-interactive (the boot's screen-on
                                       came first), ScreenOff if it is a Screen Interactive; after LogStart: Unknown (the
                                       screen state before logging began is not known)
Each Unknown block keeps what is inside it for review: uses (Activity Resumed / Paused, Keyguard Hidden, User Interaction),
lock-screen events, and boot signatures (Settings Paused with no Resumed: FallbackHome, pattern A1) - the triplets may tell
a lost screen-off from a lost power cycle.
Writes <folder>/_review/screen_blocks_<pid>.csv and screen_blocks.tsv."""
import sys, os, glob
TB = os.path.expanduser("~/workspace/eyes-toolbox")
if not os.path.isdir(TB): TB = os.path.expanduser("~/mnt/eyes-toolbox")
sys.path.insert(0, TB)
import numpy as np, pandas as pd
from eyeslib.states import device_state as ds
folder = os.path.abspath(sys.argv[1]); out = os.path.join(folder, "_review")
ON, OFF = "Screen Interactive", "Screen Non-interactive"
USE = {"Activity Resumed", "Activity Paused", "Keyguard Hidden", "User Interaction"}

def blocks_of(t, nm, pk, cyc, ci):
    """t, nm, pk: the Power Cycle's events in order. Returns its ScreenOn / ScreenOff / Unknown blocks."""
    B = []
    scr = [k for k in range(len(nm)) if nm[k] in (ON, OFF)]
    def blk(kind, k0, by0, k1, by1, why=""):
        seg = slice(k0, k1 + 1); n = nm[seg]; p = pk[seg]
        fallback = int(((n == "Activity Paused") & (p == "com.android.settings")).sum())
        B.append(dict(cycle=ci, block=kind, start_t=t[k0], end_t=t[k1], start_by=by0, end_by=by1, why=why,
                      uses=int(np.isin(n, list(USE)).sum()), keyguard_shown=int((n == "Keyguard Shown").sum()),
                      keyguard_hidden=int((n == "Keyguard Hidden").sum()), settings_paused=fallback))
    if not scr:
        blk("Unknown", 0, cyc.start, len(nm) - 1, cyc.end, "no screen events")
        return B
    first = nm[scr[0]]
    if scr[0] > 0:
        if cyc.start == "Bootup":
            blk("ScreenOn" if first == OFF else "ScreenOff", 0, "Bootup", scr[0], first)
        else:
            blk("Unknown", 0, cyc.start, scr[0], first, "screen state before logging began")
    for a_, b_ in zip(scr, scr[1:]):
        ea, eb = nm[a_], nm[b_]
        if ea == ON and eb == OFF:   blk("ScreenOn", a_, ON, b_, OFF)
        elif ea == OFF and eb == ON: blk("ScreenOff", a_, OFF, b_, ON)
        elif ea == ON:               blk("Unknown", a_, ON, b_, ON, "two Screen Interactive: screen-off lost, or shutdown + boot lost")
        else:                        blk("Unknown", a_, OFF, b_, OFF, "two Screen Non-interactive: screen-on lost, or boot + shutdown lost")
    last = scr[-1]
    if last < len(nm) - 1 or len(scr) == 1:
        blk("ScreenOn" if nm[last] == ON else "ScreenOff", last, nm[last], len(nm) - 1, cyc.end)
    return B

rows = []
for f in sorted(glob.glob(os.path.join(folder, "processed", "*_sorted_uniq_reordered.csv"))):
    pid = os.path.basename(f).split("_Chronicle")[0]
    pf = os.path.join(out, f"power_cycles_{pid}.csv")
    if not os.path.exists(pf): continue
    P = pd.read_csv(pf)
    ev = ds.load_events(f); t = ev.t.to_numpy(); nm = ev.name.to_numpy(); pk = ev.app_package_name.astype(str).to_numpy()
    allB = []
    for ci, c in P.iterrows():
        i0, i1 = np.searchsorted(t, c.start_t - 1e-3, "left"), np.searchsorted(t, c.end_t + 1e-3, "right")   # CSV rounding
        if i1 <= i0: continue
        Bs = blocks_of(t[i0:i1], nm[i0:i1], pk[i0:i1], c, ci)
        allB += Bs
    Bdf = pd.DataFrame(allB); Bdf["h"] = (Bdf.end_t - Bdf.start_t) / 3600
    Bdf.to_csv(os.path.join(out, f"screen_blocks_{pid}.csv"), index=False)
    k = Bdf.block.value_counts(); h = Bdf.groupby("block").h.sum()
    unk = Bdf[Bdf.block == "Unknown"]
    rows.append(dict(pid=pid, power_cycles=len(P), blocks=len(Bdf), ScreenOn=int(k.get("ScreenOn", 0)), ScreenOff=int(k.get("ScreenOff", 0)),
                     Unknown=int(k.get("Unknown", 0)), ScreenOn_h=round(h.get("ScreenOn", 0), 1), ScreenOff_h=round(h.get("ScreenOff", 0), 1),
                     Unknown_h=round(h.get("Unknown", 0), 1), unknown_with_boot_signature=int((unk.settings_paused > 0).sum())))
S = pd.DataFrame(rows); S.to_csv(os.path.join(out, "screen_blocks.tsv"), sep="\t", index=False)
print(S.to_string(index=False))
T = S.drop(columns="pid").sum()
span = T.ScreenOn_h + T.ScreenOff_h + T.Unknown_h
print(f"\nALL: {int(T.power_cycles)} Power Cycles -> {int(T.blocks):,} blocks: ScreenOn {int(T.ScreenOn):,} ({T.ScreenOn_h:,.0f} h), ScreenOff {int(T.ScreenOff):,} ({T.ScreenOff_h:,.0f} h), Unknown {int(T.Unknown):,} ({T.Unknown_h:,.0f} h = {100 * T.Unknown_h / span:.1f}% of logged time); Unknown blocks with a boot signature inside: {int(T.unknown_with_boot_signature)}")
