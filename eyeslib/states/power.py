"""Power-cycle track: every time the device went off (or restarted) and came back, from the boot and shutdown
markers, with how sure we are of each edge.

Ground truth (Samsung test phone, 2026-10-08, claude/shutdown-phone-test-1008.md):
  * every boot logs Screen Interactive + User Unlocked + Device Startup in the same second;
  * a clean power-off (power menu) Pauses / Stops the app in front and logs Device Shutdown in the same second;
  * after a forced restart Android stamps a Device Shutdown at its last save and loses every event after it.
A1: boots almost always leave a marker (2,110 marker boots; Startup + User Unlocked 85%, User Unlocked only 13%,
Startup only 2%); boots without any marker are rare (boot signature: a few).

One row per cycle:
  off_from      earliest time the device can have gone off (the shutdown stamp, or the last event before the boot)
  off_to        the boot (first marker), or the next event for a shutdown with no boot after
  shutdown_t    the Device Shutdown time (NaN if none was logged); shutdown_kind clean / unclean / ""
  boot_t        first boot marker time (NaN if none); boot_evidence startup+unlocked / unlocked / startup / signature / ""
  grade         confirmed  clean shutdown + boot marker: off for the whole of off_from..off_to
                likely_start  boot marker, but the shutdown is unclean or missing: a restart is certain, the device was
                              off for an unknown part of off_from..off_to (the rest: on, events lost)
                likely     boot by signature only, or a shutdown with no boot marker after it
"""
import numpy as np
import pandas as pd

from eyeslib.states import device_state as ds

BOOT_MARKERS = ["Device Startup", "User Unlocked"]
BOOT_CLUSTER_SECONDS = 60.0        # a Startup and a User Unlocked this close, with no shutdown between, are one boot
                                   # (A1: 98.2% within 1 min; test phone: same second; two boots 75 s apart seen)
DUP_SHUTDOWN_SECONDS = 60.0        # repeated Device Shutdown rows with no boot between: one shutdown
COLS = ["cycle", "off_from", "off_to", "duration_s", "shutdown_t", "shutdown_kind", "boot_t", "boot_evidence", "grade"]


def boots(ev, x=None):
    """[(index of first marker, evidence)] for marker boots, plus boots found by the boot signature only."""
    t = ev["t"].to_numpy(); nm = ev["name"].to_numpy()
    out = []; cur = None
    sd = np.where(nm == "Device Shutdown")[0]
    for i in np.where(np.isin(nm, BOOT_MARKERS))[0]:
        if cur is not None and t[i] - t[cur[0]] <= BOOT_CLUSTER_SECONDS and nm[i] not in cur[1] \
                and not ((sd > cur[0]) & (sd < i)).any():
            cur[1].add(nm[i]); continue
        if cur is not None: out.append(cur)
        cur = [i, {nm[i]}]
    if cur is not None: out.append(cur)
    res = [(i, "startup+unlocked" if len(s) == 2 else "startup" if "Device Startup" in s else "unlocked") for i, s in out]
    if x is not None:                       # signature boots: the stretch before them has the boot_signature sign
        mt = t[[i for i, _ in res]] if res else np.array([])
        for k in np.where(x["off_sign"] == ds._R["boot_signature"])[0]:
            j = k + 1
            if not len(mt) or np.abs(mt - t[j]).min() > BOOT_CLUSTER_SECONDS:
                res.append((j, "signature"))
    return sorted(res)


def power_cycles(ev, x=None):
    t = ev["t"].to_numpy(); nm = ev["name"].to_numpy(); n = len(t)
    if n < 2:
        return pd.DataFrame(columns=COLS)
    kinds = dict(ds.shutdown_kinds(ev))
    B = boots(ev, x)
    bidx = np.array([i for i, _ in B], dtype=int)
    # shutdowns, duplicates folded (a clean row wins)
    sds = []
    for i in np.where(nm == "Device Shutdown")[0]:
        if sds and t[i] - t[sds[-1][0]] <= DUP_SHUTDOWN_SECONDS and not ((bidx > sds[-1][0]) & (bidx < i)).any():
            if kinds.get(int(i)) == "clean": sds[-1][1] = "clean"
            continue
        sds.append([int(i), kinds.get(int(i), "unclean")])
    sidx = np.array([i for i, _ in sds], dtype=int)
    rows, used = [], set()
    prev_b = -1
    for bi, evid in B:
        cand = [k for k, (i, _) in enumerate(sds) if prev_b < i < bi]
        if cand:
            k = cand[0]; used.update(cand)          # the first shutdown after the previous boot
            i, kind = sds[k]; off_from, sd_t = t[i], t[i]
        else:                                       # no shutdown: off began in the longest silence before the boot
            lo = max(int(np.searchsorted(t, t[bi] - ds.BOOT_BURST_SECONDS, "left")) - 1, 0)
            g = lo + int(np.argmax(np.diff(t[lo:bi + 1]))) if bi > lo else max(bi - 1, 0)
            off_from, sd_t, kind = t[g], np.nan, ""
        if evid == "signature":
            grade = "likely"
        elif kind == "clean":
            grade = "confirmed"
        else:
            grade = "likely_start"
        rows.append([off_from, t[bi], sd_t, kind, t[bi], evid, grade])
        prev_b = bi
    for k, (i, kind) in enumerate(sds):              # shutdowns with no boot after them
        if k in used: continue
        nxt = i + 1
        while nxt < n and nm[nxt] == "Device Shutdown": nxt += 1
        rows.append([t[i], t[nxt] if nxt < n else np.nan, t[i], kind, np.nan, "", "likely"])
    P = pd.DataFrame(rows, columns=["off_from", "off_to", "shutdown_t", "shutdown_kind", "boot_t", "boot_evidence", "grade"])
    P = P.sort_values("off_from", kind="mergesort").reset_index(drop=True)
    P.insert(0, "cycle", np.arange(1, len(P) + 1)); P.insert(3, "duration_s", P.off_to - P.off_from)
    return P[COLS]
