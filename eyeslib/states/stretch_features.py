"""Feature table: one row per quiet stretch (silence of TOLERANCE_SECONDS or more), describing its two edges.

The columns are the patterns of the pattern book (claude/pattern-book.md) turned into measurements, so that the
patterns can later be combined into a categorization tree or learned by a model. Nothing here decides a label;
the current labels and rules are carried along as columns.

Edges: event k is the last event before the silence, event k+1 the first after it.
EDGE_SECONDS is the window looked at on each side (configuration changes, boots, screen events).
"""
import numpy as np
import pandas as pd

from eyeslib.states import device_state as ds

EDGE_SECONDS = 60.0
RP = ["Activity Resumed", "Activity Paused"]
SCREEN = ["Screen Interactive", "Screen Non-interactive"]
BOOT = ["Device Startup", "User Unlocked"]
RULE_NAMES = np.array(ds.RULES + [""], dtype=object)


def _count_in(sorted_t, lo, hi):
    """number of times in sorted_t within [lo, hi]"""
    return np.searchsorted(sorted_t, hi, "right") - np.searchsorted(sorted_t, lo, "left")


def _last_le(idx, k):
    """position in idx of the last element <= k (-1 if none)"""
    return np.searchsorted(idx, k, "right") - 1


def _first_ge(idx, k):
    """position in idx of the first element >= k (len(idx) if none)"""
    return np.searchsorted(idx, k, "left")


def _event_arrays(ev):
    t = ev["t"].to_numpy(); nm = ev["name"].to_numpy(); pk = ev["app_package_name"].astype(str).to_numpy()
    s = pd.Series(pk)
    system = (s.str.contains(ds.NON_USER_APP) | s.str.contains(ds.LOCKSCREEN_FEED_APP) | s.str.contains(ds.SYSTEM_BOOT_APP)).to_numpy()
    # for every Resumed / Paused: was the same app's previous Resumed / Paused a Resumed? (False = unpaired)
    rp = np.where(np.isin(nm, RP))[0]
    prev_res = np.zeros(len(nm), dtype=bool); last = {}
    for i in rp:
        prev_res[i] = last.get(pk[i]) == "Activity Resumed"
        last[pk[i]] = nm[i]
    # services open just after each event (apps whose last service event is a Start)
    open_n = np.zeros(len(nm), dtype=np.int16); run = set()
    for i in range(len(nm)):
        if nm[i] == "Foreground Service Start":
            run.add(pk[i])
        elif nm[i] == "Foreground Service Stop":
            run.discard(pk[i])
        elif nm[i] in ("Device Shutdown", "Device Startup"):
            run.clear()
        open_n[i] = len(run)
    return t, nm, pk, system, rp, prev_res, open_n


def stretch_features(ev, x, local_hour=None):
    """DataFrame, one row per quiet stretch. ev: load_events output; x: interval_labels output (same ev);
    local_hour: optional array (per event) of the local hour, for the time of day of each stretch."""
    if x is None:
        return pd.DataFrame()
    t, nm, pk, system, rp, prev_res, open_n = _event_arrays(ev)
    d = x["d"]; k = np.where(d >= ds.TOLERANCE_SECONDS)[0]; a, b = t[k], t[k + 1]
    cc_t = t[nm == "Configuration Change"]; bt_t = t[np.isin(nm, BOOT)]
    scr = np.where(np.isin(nm, SCREEN))[0]
    if not len(k):
        return pd.DataFrame()
    # empty index arrays: point at event 0 and mark "not found" through the ok masks below
    scr_ = scr if len(scr) else np.array([0]); rp_ = rp if len(rp) else np.array([0])
    f = dict(stretch=k + 1, start=a, end=b, duration_s=d[k],
             strict=[ds.LABELS[int(v)] for v in x["strict"][k]], likely=[ds.LABELS[int(v)] for v in x["likely"][k]],
             rule_strict=RULE_NAMES[x["r_strict"][k]], rule_likely=RULE_NAMES[x["r_likely"][k]],
             off_sign=RULE_NAMES[x["off_sign"][k]], on_sign=RULE_NAMES[x["on_sign"][k]], boot_score=x["boot_score"][k],
             screen_base=[ds.LABELS.get(int(v), "") for v in x["screen"][k]])
    if local_hour is not None:
        f["hour_local"] = np.asarray(local_hour)[k]
    # before the silence
    f["before_event"] = nm[k]; f["before_app"] = pk[k]; f["before_system"] = system[k]
    f["before_config_n"] = _count_in(cc_t, a - EDGE_SECONDS, a)
    f["before_services_open"] = open_n[k]
    j = _last_le(scr, k) if len(scr) else np.full(len(k), -1); ok = j >= 0
    f["before_screen"] = np.where(ok, np.where(nm[scr_[np.maximum(j, 0)]] == "Screen Interactive", "on", "off"), "unknown")
    f["before_screen_age_s"] = np.where(ok, a - t[scr_[np.maximum(j, 0)]], np.nan)
    j = _last_le(rp, k) if len(rp) else np.full(len(k), -1); ok = j >= 0; e = rp_[np.maximum(j, 0)]
    front = ok & (nm[e] == "Activity Resumed")
    f["front_app"] = np.where(front, pk[e], ""); f["front_system"] = front & system[e]
    f["front_age_s"] = np.where(front, a - t[e], np.nan)
    f["before_shutdown"] = np.isin(nm[k], ["Device Shutdown"])
    # after the silence
    f["after_event"] = nm[k + 1]; f["after_app"] = pk[k + 1]; f["after_system"] = system[k + 1]
    f["after_config_n"] = _count_in(cc_t, b, b + EDGE_SECONDS)
    f["after_boot"] = _count_in(bt_t, b, b + EDGE_SECONDS) > 0
    j = _first_ge(scr, k + 1); ok = j < len(scr); e = scr[np.minimum(j, len(scr) - 1)] if len(scr) else np.zeros(len(k), int)
    f["after_screen"] = np.where(ok, np.where(nm[e] == "Screen Interactive", "on", "off"), "none")
    f["after_screen_lag_s"] = np.where(ok, t[e] - b, np.nan)
    j = _first_ge(rp, k + 1); ok = j < len(rp); e = rp[np.minimum(j, len(rp) - 1)] if len(rp) else np.zeros(len(k), int)
    f["after_rp_event"] = np.where(ok, nm[e], ""); f["after_rp_app"] = np.where(ok, pk[e], "")
    f["after_rp_system"] = ok & system[e]; f["after_rp_lag_s"] = np.where(ok, t[e] - b, np.nan)
    f["after_rp_unpaired_pause"] = ok & (nm[e] == "Activity Paused") & ~prev_res[e]
    f["after_rp_same_as_front"] = ok & (f["front_app"] != "") & (pk[e] == f["front_app"])
    # an unpaired user-app Paused in the first burst after the silence (the next app's Resumed may come first)
    burst = np.zeros(len(k), dtype=bool); burst_app = np.full(len(k), "", dtype=object)
    for n, (kk, bb) in enumerate(zip(k, b)):
        lo = _first_ge(rp, kk + 1); hi = lo
        if lo >= len(rp):
            continue
        while hi < len(rp) and t[rp[hi]] <= t[rp[lo]] + 1.0:
            hi += 1
        for i in rp[lo:hi]:
            if nm[i] == "Activity Paused" and not prev_res[i] and not system[i]:
                burst[n], burst_app[n] = True, pk[i]; break
    f["after_burst_unpaired_user_pause"] = burst; f["after_burst_pause_app"] = burst_app
    return pd.DataFrame(f)
