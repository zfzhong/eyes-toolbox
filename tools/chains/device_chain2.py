"""device_chain2.py <category folder>: device-state chains, event order only (David, 10-15 / 10-16).
  "only the first event is bootup, and the last event is shutdown ... start -> screen-on ... -> end"
  "if there is one shutdown, it actually ends a state-chain. The next chain has to start, even without a bootup event -- the
   bootup event is lost ... the next start is not supported by a bootup event, but supported by a previous shutdown event.
   Similarly, a bootup event starts state-chain, it also ends a previous state-chain."
Boundaries: every Device Shutdown ends a chain (it is the chain's last event); every boot (Device Startup / User Unlocked,
each at most once per boot) starts a chain and ends the previous one. A boot's start is the earliest event of the boot's own
run ahead of the marker (walking back over events that are not app use, not past a screen-off or the previous chain).
Support:
  start   "boot"           the chain begins with a boot
          "prev shutdown"  the previous chain ended with a Shutdown (the boot was not logged)
          "file start"     the first chain of the file starts at the file's first event (David, 10-16)
  end     "shutdown"       the chain ends with a Shutdown
          "next boot"      a boot follows (power was lost: no shutdown logged)
          "file end"       the last chain ends at the file's last event
  complete = start and end both supported (so every chain is complete by construction); "own markers" = boot and shutdown.
  Names (David, 10-16): start = Bootup (own boot marker) or LogStart (file start, or after a shutdown with no boot logged:
  powered on, logging began later); end = Shutdown (own) or LogEnd (file end, or before a boot with no shutdown logged:
  logging ended, the device went down later). Only Bootup / Shutdown are power-on / power-off.
  What a chain cannot show by itself: a power cycle inside it whose boot and shutdown were both lost (a false positive);
  the app triplet chains reveal it. Screen repeats inside a chain are failures of the screen story.
Inside a chain the screen alternates on/off; repeats (on-on, off-off) are counted, not cut.
Writes <folder>/_review/device_chains2_<pid>.csv and device_chains2.tsv."""
import sys, os, glob, collections
TB = os.path.expanduser("~/workspace/eyes-toolbox")
if not os.path.isdir(TB): TB = os.path.expanduser("~/mnt/eyes-toolbox")
sys.path.insert(0, TB)
import numpy as np, pandas as pd
from eyeslib.states import device_state as ds
folder = os.path.abspath(sys.argv[1]); out = os.path.join(folder, "_review"); os.makedirs(out, exist_ok=True)
BOOT = {"Device Startup", "User Unlocked"}; ON, OFF, SHUT = "Screen Interactive", "Screen Non-interactive", "Device Shutdown"
USE = {"Activity Resumed", "Activity Paused", "Activity Stopped", "User Interaction", "Keyguard Hidden"}
QUIET = {"Standby Bucket Changed", "Notification Interruption", "Notification Seen"}

def chains_of(ev):
    t = ev.t.to_numpy(); nm = ev.name.to_numpy(); n = len(t)
    idx = np.where(~np.isin(nm, list(QUIET)))[0]
    bounds = []                      # (start k, how it starts)
    cur_start, how, seen = 0, "file start", set()
    ends = []                        # (end k inclusive, how it ends)
    k = 0
    for k, i in enumerate(idx):
        e = nm[i]
        if e == SHUT:
            ends.append((k, "shutdown")); bounds.append((cur_start, how))
            cur_start, how, seen = k + 1, "prev shutdown", set(); continue
        if e in BOOT:
            if how == "boot" and e not in seen:
                seen.add(e); continue                       # the other marker of the same boot
            if how == "prev shutdown" and not seen:
                how, seen = "boot", {e}; continue           # the first boot after a shutdown is this power cycle's boot
                                                            # (its run - screen-on, FallbackHome - may be logged before it)
            # a boot while a chain is open: it ends that chain; walk back over the boot's own run
            j = k
            while j - 1 >= cur_start and nm[idx[j - 1]] not in USE and nm[idx[j - 1]] != OFF:
                j -= 1
            if j > cur_start:
                ends.append((j - 1, "next boot")); bounds.append((cur_start, how))
            cur_start, how, seen = j, "boot", {e}
    if cur_start <= len(idx) - 1:
        ends.append((len(idx) - 1, "file end")); bounds.append((cur_start, how))
    rows = []
    for (s0, hs), (e0, he) in zip(bounds, ends):
        seg = idx[s0:e0 + 1]
        if len(seg) == 0: continue
        names = nm[seg]; scr = [x for x in names if x in (ON, OFF)]
        rows.append(dict(start_t=t[seg[0]], end_t=t[seg[-1]], start_event=names[0], end_event=names[-1], start_by=hs, end_by=he,
                         screen_cycles=int((names == ON).sum()), screen_repeats=sum(1 for a_, b_ in zip(scr, scr[1:]) if a_ == b_),
                         on_on=sum(1 for a_, b_ in zip(scr, scr[1:]) if a_ == b_ == ON), off_off=sum(1 for a_, b_ in zip(scr, scr[1:]) if a_ == b_ == OFF)))
    C = pd.DataFrame(rows)
    # David, 10-16: "only when it is supported by a bootup/shutdown, we can say it's power-on/off ... we can use
    # LogStart/Bootup for starting, and LogEnd/Shutdown for ending." The detail (file edge, after a shutdown, before a boot)
    # is kept in start_by / end_by.
    C["start"] = np.where(C.start_by == "boot", "Bootup", "LogStart")
    C["end"] = np.where(C.end_by == "shutdown", "Shutdown", "LogEnd")
    # David, 10-16: the physical start / end of the file is also a start / end ("supported by the physical start/end of a file")
    ss = C.start_by.isin(["boot", "prev shutdown", "file start"]); es = C.end_by.isin(["shutdown", "next boot", "file end"])
    C["type"] = np.select([ss & es, ~ss & es, ss & ~es], ["complete", "no start", "no end"], "no start-end")
    # David, 10-16: two consecutive screen-on (or screen-off) events inside a state chain contradict it (one was lost)
    C["contradictory"] = C.screen_repeats > 0
    C["own_markers"] = (C.start_by == "boot") & (C.end_by == "shutdown")
    C["h"] = (C.end_t - C.start_t) / 3600
    return C

rows = []
for f in sorted(glob.glob(os.path.join(folder, "processed", "*_sorted_uniq_reordered.csv"))):
    pid = os.path.basename(f).split("_Chronicle")[0]
    ev = ds.load_events(f); C = chains_of(ev)
    C.to_csv(os.path.join(out, f"device_chains2_{pid}.csv"), index=False)
    n = C.type.value_counts(); span = (ev.t.iloc[-1] - ev.t.iloc[0]) / 3600
    combo = (C.start + "->" + C.end).value_counts()
    rows.append(dict(pid=pid, days=round(span / 24, 1), chains=len(C), **{k: int(combo.get(k, 0)) for k in ["Bootup->Shutdown", "Bootup->LogEnd", "LogStart->Shutdown", "LogStart->LogEnd"]}, **{k: int(n.get(k, 0)) for k in ["complete", "no start", "no end", "no start-end"]},
                     own_markers=int(C.own_markers.sum()), start_prev_shutdown=int((C.start_by == "prev shutdown").sum()), end_next_boot=int((C.end_by == "next boot").sum()),
                     screen_repeats=int(C.screen_repeats.sum()), contradictory=int(C.contradictory.sum()), on_on=int(C.on_on.sum()), off_off=int(C.off_off.sum()), complete_time_pct=round(100 * C.h[C.type == "complete"].sum() / span, 1)))
S = pd.DataFrame(rows); S.to_csv(os.path.join(out, "device_chains2.tsv"), sep="\t", index=False)
print(S.to_string(index=False))
print("\nchains with two consecutive screen-on or screen-off:", int(S.contradictory.sum()), "of", int(S.chains.sum()), "| on-on", int(S.on_on.sum()), "off-off", int(S.off_off.sum()))
print("start -> end:", S[["Bootup->Shutdown", "Bootup->LogEnd", "LogStart->Shutdown", "LogStart->LogEnd"]].sum().to_dict())
T = S[["chains", "complete", "no start", "no end", "no start-end", "own_markers", "start_prev_shutdown", "end_next_boot", "screen_repeats"]].sum()
print(f"\nALL: {int(T.chains)} chains: complete {int(T.complete)} (by own boot and shutdown {int(T.own_markers)}), no start {int(T['no start'])}, no end {int(T['no end'])}, no start-end {int(T['no start-end'])}")
print(f"starts supported by a previous shutdown (boot not logged): {int(T.start_prev_shutdown)}; ends supported by the next boot (no shutdown logged): {int(T.end_next_boot)}; screen repeats inside chains: {int(T.screen_repeats)}")
