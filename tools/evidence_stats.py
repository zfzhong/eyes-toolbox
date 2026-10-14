"""
Evidence statistics for one processing-group folder (e.g. by_group/A1).

For every raw file it measures
  A. how unreliable the raw log is (duplicates, order, missing events, gaps, ties);
  B. how much of the reconstruction is observed vs inferred (sessions, links);
  C. whether the two independent timelines agree: app sessions (from app
     events only) vs device states (from screen, keyguard and power events).

Usage: python tools/evidence_stats.py <group_dir> --out evidence.csv
"""
import argparse
import glob
import os
import time

import numpy as np
import pandas as pd

SI = {"Screen Interactive", "Unknown importance: 15"}
SNI = {"Screen Non-interactive", "Unknown importance: 16"}
RES = {"Activity Resumed", "Move to Foreground"}
PAU = {"Activity Paused", "Move to Background"}
STOP = {"Activity Stopped", "Unknown importance: 23"}
SHUT = {"Device Shutdown", "Unknown importance: 26"}
BOOT = {"Device Startup", "Unknown importance: 27"}
OBSERVED_ENDS = {"Paused", "killed"}   # the session's last app left the foreground by its own logged event


def secs(s):
    t = pd.to_datetime(s, utc=True, format="ISO8601", errors="coerce")
    return (t.astype("int64") / 1e9).where(t.notna())


def union(iv):
    iv = np.asarray(iv, dtype=float).reshape(-1, 2)
    iv = iv[~np.isnan(iv).any(axis=1)]
    iv = iv[iv[:, 1] > iv[:, 0]]
    if not len(iv):
        return iv
    iv = iv[np.argsort(iv[:, 0], kind="mergesort")]
    out = [list(iv[0])]
    for s, e in iv[1:]:
        if s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return np.array(out)


def length(u):
    return float((u[:, 1] - u[:, 0]).sum()) if len(u) else 0.0


def inter(a, b):
    i = j = 0
    tot = 0.0
    while i < len(a) and j < len(b):
        lo, hi = max(a[i, 0], b[j, 0]), min(a[i, 1], b[j, 1])
        if hi > lo:
            tot += hi - lo
        if a[i, 1] < b[j, 1]:
            i += 1
        else:
            j += 1
    return tot


def one_file(folder, raw_path):
    name = os.path.basename(raw_path)
    stem = name[:-4].replace(" ", "_") + "_sorted_uniq_reordered"
    proc = os.path.join(folder, "processed")
    tok = name.split("_")
    r = dict(folder=os.path.basename(folder), file=name, participant=tok[0] + "_" + tok[1],
             role="parent" if tok[1].startswith("P") else "child")

    # ---- A. raw log reliability
    raw = pd.read_csv(raw_path, low_memory=False)
    r["raw_rows"] = len(raw)
    r["dup_rows"] = int(raw.duplicated().sum())
    t = secs(raw["event_timestamp"])
    back = t.diff() < 0
    r["out_of_order_rows"] = int(back.sum())
    r["span_h"] = float((t.max() - t.min()) / 3600)

    ev = pd.read_csv(os.path.join(proc, stem + ".csv"), usecols=["app_package_name", "interaction_type", "event_timestamp"],
                     low_memory=False)
    ev["t"] = secs(ev["event_timestamp"])
    it = ev["interaction_type"]

    # screen on/off pairing: two "on" in a row = a missing "off", and vice versa
    sc = ev[it.isin(SI | SNI)].sort_values("t", kind="mergesort")
    on = sc["interaction_type"].isin(SI).to_numpy()
    r["screen_on"] = int(on.sum())
    r["screen_off"] = int((~on).sum())
    r["screen_on_without_off"] = int((on[1:] & on[:-1]).sum())
    r["screen_off_without_on"] = int((~on[1:] & ~on[:-1]).sum())

    # power pairing
    r["shutdowns"] = int(it.isin(SHUT).sum())
    r["startups"] = int(it.isin(BOOT).sum())

    # timestamp ties: an app's Resumed at exactly the same millisecond as another app's Paused
    rp = ev[it.isin(RES | PAU)]
    res_t = rp.loc[rp["interaction_type"].isin(RES), ["t", "app_package_name"]]
    pau_t = rp.loc[rp["interaction_type"].isin(PAU), ["t", "app_package_name"]]
    m = res_t.merge(pau_t, on="t", suffixes=("_r", "_p"))
    r["resumes"] = len(res_t)
    r["resume_tied_with_other_pause"] = int((m["app_package_name_r"] != m["app_package_name_p"]).sum())

    # ---- device-state blocks
    blocks = pd.read_csv(os.path.join(proc, "segments", stem + "_BLOCKS.csv"))
    blocks["s"], blocks["e"] = secs(blocks["start_ts"]), secs(blocks["end_ts"])
    blocks = blocks.dropna(subset=["s", "e"])
    u = {k: union(blocks.loc[blocks.block_type == k, ["s", "e"]].to_numpy())
         for k in ["SHUTDOWN", "GAP", "IDLE", "GLANCE"]}
    all_blocks = union(blocks[["s", "e"]].to_numpy())
    for k, v in u.items():
        r[f"{k.lower()}_h"] = length(v) / 3600
    span = np.array([[t.min(), t.max()]])
    active_len = float(t.max() - t.min()) - inter(all_blocks, span)
    r["active_h"] = active_len / 3600

    # ---- B. sessions: observed vs inferred
    sp = os.path.join(proc, "sessions", stem + "_SESSION.csv")
    s = pd.read_csv(sp)
    a = pd.read_csv(sp.replace("_SESSION.csv", "_SESSION_APPS.csv"))
    r["sessions"] = len(s)
    r["session_h"] = float(s["duration_s"].sum() / 3600)
    obs_end = s["end_evidence"].isin(OBSERVED_ENDS)
    fully = obs_end & (s["links_inferred"] == 0)
    r["sessions_end_observed"] = int(obs_end.sum())
    r["sessions_fully_observed"] = int(fully.sum())
    r["session_h_fully_observed"] = float(s.loc[fully, "duration_s"].sum() / 3600)
    for k in ["Paused", "killed", "next_resumed", "screen_off", "shutdown", "end_of_log"]:
        r[f"app_end_{k}"] = int((a["end_evidence"] == k).sum())
    links = a["link_from_previous"].fillna("")
    links = links[links != ""]
    for k in ["full", "paused_resumed", "resumed_only", "stopped_resumed"]:
        r[f"link_{k}"] = int((links == k).sum())

    # ---- C. agreement between app sessions and device states
    su = union(np.c_[secs(s["start_time"]), secs(s["end_time"])])
    r["session_h_in_active"] = (length(su) - inter(su, all_blocks)) / 3600
    for k, v in u.items():
        r[f"session_h_in_{k.lower()}"] = inter(su, v) / 3600
    r["active_h_with_session"] = r["session_h_in_active"]
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("group_dir")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    rows = []
    for folder in sorted(glob.glob(os.path.join(a.group_dir, "*"))):
        if not os.path.isdir(folder) or os.path.basename(folder).startswith("_"):
            continue
        for raw in sorted(glob.glob(os.path.join(folder, "*.csv"))):
            t0 = time.time()
            try:
                rows.append(one_file(folder, raw))
            except Exception as e:  # keep going, report at the end
                rows.append(dict(folder=os.path.basename(folder), file=os.path.basename(raw), error=repr(e)))
            print(f"{os.path.basename(raw)[:40]:40s} {time.time()-t0:5.1f}s", flush=True)
            pd.DataFrame(rows).to_csv(a.out, index=False)
    print("ALL_DONE")


if __name__ == "__main__":
    main()
