"""
Independent verification of EYES toolbox outputs.

Usage: python verify_results.py <cohort_dir> [<cohort_dir> ...] --out report.csv

For every participant file in <cohort_dir>/processed it recomputes invariants
from the raw data and the intermediate outputs, without reusing toolbox code.
All durations are in seconds.
"""
import argparse
import glob
import os
import sys
import time

import numpy as np
import pandas as pd

NS = 1e9


# ---------------------------------------------------------------- intervals
def to_sec(s):
    t = pd.to_datetime(s, utc=True, format="ISO8601", errors="coerce")
    return t.astype("int64").where(t.notna(), np.nan) / NS


def union(iv):
    """iv: array (n,2) -> merged non-overlapping array."""
    iv = np.asarray(iv, dtype=float)
    if len(iv) == 0:
        return iv.reshape(0, 2)
    iv = iv[~np.isnan(iv).any(axis=1)]
    iv = iv[iv[:, 1] > iv[:, 0]]
    if len(iv) == 0:
        return iv.reshape(0, 2)
    iv = iv[np.argsort(iv[:, 0], kind="mergesort")]
    out = [list(iv[0])]
    for s, e in iv[1:]:
        if s <= out[-1][1]:
            if e > out[-1][1]:
                out[-1][1] = e
        else:
            out.append([s, e])
    return np.array(out)


def length(u):
    return float((u[:, 1] - u[:, 0]).sum()) if len(u) else 0.0


def inter_len(a, b):
    """length of intersection of two unions."""
    i = j = 0
    tot = 0.0
    while i < len(a) and j < len(b):
        lo = max(a[i, 0], b[j, 0])
        hi = min(a[i, 1], b[j, 1])
        if hi > lo:
            tot += hi - lo
        if a[i, 1] < b[j, 1]:
            i += 1
        else:
            j += 1
    return tot


def self_overlap(iv):
    """sum of lengths - union length = double-counted seconds."""
    iv = np.asarray(iv, dtype=float)
    iv = iv[~np.isnan(iv).any(axis=1)] if len(iv) else iv
    if len(iv) == 0:
        return 0.0
    tot = float(np.clip(iv[:, 1] - iv[:, 0], 0, None).sum())
    return tot - length(union(iv))


def coverage_fraction(rows, u):
    """for each row interval, fraction covered by union u."""
    out = np.zeros(len(rows))
    if len(u) == 0 or len(rows) == 0:
        return out
    starts = u[:, 0]
    cum = np.concatenate([[0], np.cumsum(u[:, 1] - u[:, 0])])

    def covered_until(t):
        k = np.searchsorted(starts, t, side="right")  # intervals with start <= t
        base = cum[np.maximum(k - 1, 0)]
        last = np.where(k > 0, np.clip(t - u[np.maximum(k - 1, 0), 0], 0,
                                       u[np.maximum(k - 1, 0), 1] - u[np.maximum(k - 1, 0), 0]), 0)
        return np.where(k > 0, base + last, 0)

    s, e = rows[:, 0], rows[:, 1]
    d = e - s
    cov = covered_until(e) - covered_until(s)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(d > 0, cov / d, 0)
    return out


# ---------------------------------------------------------------- helpers
def read(path, **kw):
    try:
        return pd.read_csv(path, low_memory=False, **kw)
    except Exception:
        return None


def key_of(name):
    t = name.split("_")
    return t[0] + "_" + t[1]


def check_participant(proc, reordered):
    r = {}
    base = os.path.basename(reordered)[: -len(".csv")]
    key = key_of(base)
    r["participant"] = key
    stem = base[: -len("_sorted_uniq_reordered")]
    cohort_dir = os.path.dirname(proc)

    # ---- A. preprocessing row accounting
    raws = [f for f in glob.glob(os.path.join(cohort_dir, "*.csv"))
            if key_of(os.path.basename(f)) == key]
    raw = read(raws[0]) if raws else None
    srt = read(os.path.join(proc, stem + "_sorted.csv"))
    unq = read(os.path.join(proc, stem + "_sorted_uniq.csv"))
    reo = read(reordered)
    r["raw_rows"] = len(raw) if raw is not None else np.nan
    r["sorted_rows"] = len(srt) if srt is not None else np.nan
    r["uniq_rows"] = len(unq) if unq is not None else np.nan
    r["reordered_rows"] = len(reo) if reo is not None else np.nan
    if raw is not None:
        norm = raw.copy()
        norm["event_timestamp"] = pd.to_datetime(norm["event_timestamp"], format="mixed", utc=True)
        r["raw_exact_dup_rows"] = int(norm.duplicated().sum())
    if unq is not None:
        r["uniq_residual_dup_rows"] = int(unq.duplicated().sum())
        mono = to_sec(unq["event_timestamp"]).diff().dropna()
        r["uniq_non_monotonic"] = int((mono < 0).sum())

    ev = reo if reo is not None else unq
    it = ev["interaction_type"].value_counts() if ev is not None else pd.Series(dtype=int)
    r["n_screen_interactive"] = int(it.get("Screen Interactive", 0) + it.get("Unknown importance: 15", 0))
    r["n_keyguard_hidden"] = int(it.get("Keyguard Hidden", 0) + it.get("Unknown importance: 18", 0))
    r["n_resumed"] = int(it.get("Activity Resumed", 0) + it.get("Move to Foreground", 0))
    r["n_stopped"] = int(it.get("Activity Stopped", 0) + it.get("Unknown importance: 23", 0))
    if ev is not None and len(ev):
        ts = to_sec(ev["event_timestamp"])
        r["span_hours"] = (ts.max() - ts.min()) / 3600
        span = (ts.min(), ts.max())
    else:
        span = None

    # ---- B. blocks
    seg = os.path.join(proc, "segments")
    blk = read(os.path.join(seg, base + "_BLOCKS.csv"))
    bl_u = np.zeros((0, 2))
    bl5_u = np.zeros((0, 2))
    if blk is not None:
        blk["s"] = to_sec(blk["start_ts"])
        blk["e"] = to_sec(blk["end_ts"])
        paired = blk.dropna(subset=["s", "e"])
        r["blocks_unpaired_rows"] = len(blk) - len(paired)
        r["blocks_negative"] = int((paired["e"] < paired["s"]).sum())
        for t in ["SHUTDOWN", "IDLE", "GAP", "GLANCE"]:
            p = paired[paired.block_type == t]
            r[f"{t.lower()}_hours"] = (p["e"] - p["s"]).clip(lower=0).sum() / 3600
        iv = paired[["s", "e"]].to_numpy()
        r["blocks_overlap_hours"] = self_overlap(iv) / 3600
        # overlap between specific type pairs
        for a, b in [("IDLE", "SHUTDOWN"), ("IDLE", "GAP"), ("GLANCE", "IDLE"), ("SHUTDOWN", "GAP")]:
            ua = union(paired[paired.block_type == a][["s", "e"]].to_numpy())
            ub = union(paired[paired.block_type == b][["s", "e"]].to_numpy())
            r[f"overlap_{a}_{b}_hours"] = inter_len(ua, ub) / 3600
        bl_u = union(iv)
        p5 = paired[(paired.e - paired.s) >= 5]
        bl5_u = union(p5[["s", "e"]].to_numpy())
        if span:
            tot = span[1] - span[0]
            r["active_complement_hours_true"] = (tot - inter_len(bl_u, np.array([span]))) / 3600

    # ---- C. pickups
    pk = read(os.path.join(seg, base + "_PICKUPS.csv"))
    if pk is not None and len(pk):
        pk["s"] = to_sec(pk["start_ts"])
        pk["e"] = to_sec(pk["end_ts"])
        act = pk[pk.block_type == "ACTIVE"]
        au = union(act[["s", "e"]].to_numpy())
        r["pickups_n_active"] = len(act)
        r["pickups_active_hours"] = (act.e - act.s).sum() / 3600
        r["pickups_active_inside_blocks_hours"] = inter_len(au, bl_u) / 3600
        r["pickups_active_over_6h"] = int(((act.e - act.s) > 6 * 3600).sum())
        r["pickups_active_self_overlap_hours"] = self_overlap(act[["s", "e"]].to_numpy()) / 3600

    # ---- D. activity level
    act1 = read(os.path.join(proc, base + "_act_one.csv"))
    if act1 is not None and len(act1):
        rs, ps, ss = to_sec(act1.resume_time), to_sec(act1.pause_time), to_sec(act1.stop_time)
        r["act_rows"] = len(act1)
        r["act_resume_only"] = int((rs.notna() & ps.isna() & ss.isna()).sum())
        r["act_no_resume"] = int(rs.isna().sum())
        has_rp = rs.notna() & ps.notna()
        r["act_duration_eq_pause_minus_resume"] = float(
            (np.isclose(act1.duration[has_rp], (ps - rs)[has_rp], atol=0.002)).mean()) if has_rp.any() else np.nan
        has_rs = rs.notna() & ss.notna()
        r["act_rows_with_stop"] = int(has_rs.sum())
        r["act_stop_minus_pause_hours"] = float(((ss - ps)[has_rs & ps.notna()]).clip(lower=0).sum() / 3600)

    # ---- E. app level vs nested
    app = read(os.path.join(proc, key + "_app_1.csv"))
    nes = read(os.path.join(proc, key + "_primary_secondary_nested.csv"))
    app_u = np.zeros((0, 2))
    if app is not None and len(app):
        app["s"], app["e"] = to_sec(app.resume_time), to_sec(app.end_time)
        app_u = union(app[["s", "e"]].to_numpy())
        r["app_chunks"] = len(app)
        r["app_sum_hours"] = (app.e - app.s).sum() / 3600
        r["app_union_hours"] = length(app_u) / 3600
        r["app_chunks_over_3h"] = int(((app.e - app.s) > 3 * 3600).sum())
        r["app_chunks_over_3h_hours"] = float((app.e - app.s)[(app.e - app.s) > 3 * 3600].sum() / 3600)
    if nes is not None and len(nes):
        nes["s"], nes["e"] = to_sec(nes.resume_time), to_sec(nes.end_time)
        prim = nes[nes.duration > 0]
        pu = union(prim[["s", "e"]].to_numpy())
        r["nested_primary_sum_hours"] = prim.duration.sum() / 3600
        r["nested_primary_union_hours"] = length(pu) / 3600
        r["nested_primary_self_overlap_hours"] = self_overlap(prim[["s", "e"]].to_numpy()) / 3600
        if len(app_u):
            r["app_time_missing_from_primary_hours"] = (length(app_u) - inter_len(app_u, pu)) / 3600
            r["app_time_missing_pct"] = 100 * (1 - inter_len(app_u, pu) / length(app_u))
            # chunks entirely lost (no row at all for that app overlapping it)
            lost = 0
            for a, g in app.groupby("app_package_name"):
                nu = union(nes[nes.app_package_name == a][["s", "e"]].to_numpy())
                cf = coverage_fraction(g[["s", "e"]].to_numpy(), nu)
                lost += int(((cf < 0.01) & ((g.e - g.s) > 0).to_numpy()).sum())
            r["app_chunks_lost_in_nested"] = lost

    # ---- F. merge (status labelling) + conservation
    fau = read(os.path.join(proc, key + "_primary_secondary_fau.csv"))
    if fau is not None and len(fau) and nes is not None:
        nz = nes[~((nes.duration == 0) & (nes.secondary_duration == 0))]
        r["merge_conservation_diff_s"] = float(
            (fau.duration.sum() + fau.secondary_duration.sum()) - (nz.duration.sum() + nz.secondary_duration.sum()))
        fau["s"], fau["e"] = to_sec(fau.resume_time), to_sec(fau.end_time)
        cf = coverage_fraction(fau[["s", "e"]].to_numpy(), bl5_u)
        d = (fau.e - fau.s).to_numpy()
        isact = (fau.device_status == "ACTIVE").to_numpy()
        wrong_act = isact & (cf > 0.5)
        wrong_blk = (~isact) & (cf < 0.5)
        r["merge_mislabel_active_hours"] = float(d[wrong_act].sum() / 3600)
        r["merge_mislabel_nonactive_hours"] = float(d[wrong_blk].sum() / 3600)
        r["merge_status_counts"] = ";".join(f"{k}={v}" for k, v in fau.device_status.value_counts().items())

    # ---- G. FAU usage
    fu = read(os.path.join(proc, key + "_fau_usage.csv"))
    if fu is not None and fau is not None and len(fau):
        exp = fau[(fau.device_status == "ACTIVE") & (fau.duration > 0)].duration.sum()
        r["fau_usage_hours"] = fu.duration.sum() / 3600
        r["fau_usage_diff_s"] = float(fu.duration.sum() - exp)
        # FAU if nothing had been lost by the nested step: app union outside blocks
        if len(app_u):
            r["fau_expected_if_no_loss_hours"] = (length(app_u) - inter_len(app_u, bl5_u)) / 3600

    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--budget", type=float, default=0,
                    help="stop starting new participants after this many seconds (0 = no limit); "
                         "re-run with the same --out to resume")
    a = ap.parse_args()
    rows, done = [], set()
    if os.path.exists(a.out):
        prev = pd.read_csv(a.out)
        rows = prev.to_dict("records")
        done = set(zip(prev.cohort_dir, prev.participant))
    start = time.time()
    for d in a.dirs:
        proc = os.path.join(d, "processed")
        files = sorted(glob.glob(os.path.join(proc, "*_sorted_uniq_reordered.csv")))
        for f in files:
            if (d, key_of(os.path.basename(f))) in done:
                continue
            if a.budget and time.time() - start > a.budget:
                print("BUDGET_EXHAUSTED")
                return
            t0 = time.time()
            try:
                r = check_participant(proc, f)
            except Exception as e:  # keep going
                r = {"participant": key_of(os.path.basename(f)), "error": repr(e)}
            r["cohort_dir"] = d
            rows.append(r)
            print(f"{r['participant']:<14} {time.time()-t0:5.1f}s", flush=True)
            pd.DataFrame(rows).to_csv(a.out, index=False)
    print("ALL_DONE")


if __name__ == "__main__":
    main()
