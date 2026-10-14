"""
Load a processing-group folder (e.g. by_group/A1) into a SQLite database for the
local review app.

Tables
    files        one row per raw log file
    blocks       device-state blocks (SHUTDOWN, GAP, IDLE, GLANCE)
    sessions     app-usage sessions, with review flags
    session_apps the chain of apps in each session
    app_usage    seconds per local day and app (split at local midnight)
    events       raw events around flagged sessions (for the review screen)
    verdicts     human verdicts; kept when the data tables are rebuilt

Displays
    Sessions on the car display (Android Auto, eyeslib.usage.car_display) are
    kept and reported separately; they are never flagged for screen-off time.

Review flags (a session needs a person to look at it when any is set)
    gap            the session contains a silence >= GAP_SECONDS with no event
                   of any kind: we cannot tell whether the app stayed on screen
    idle           >= IDLE_MIN_SECONDS and >= IDLE_MIN_SHARE of the session
                   falls in IDLE (screen off): plausible for navigation or
                   music, not for most apps
    long_inferred  the session's end was not observed (screen off, shutdown,
                   end of log) and it lasted >= LONG_INFERRED_SECONDS

Heartbeat evidence (shown to the reviewer; no thresholds, no flags)
    Events are classed as usage, state or heartbeat (eyeslib.core.event_classes).
    For each session: the longest stretch with no usage or state event ("quiet"),
    the heartbeats inside that stretch, event counts by class, and the last
    usage event. Heartbeats in a quiet stretch mean the device was on but
    nobody used it; none at all means it was asleep, off or not logging.

Boot signature after the longest silence (shown to the reviewer; no thresholds, no flags)
    The first Activity Resumed / Paused at or after the silence ends. It is an
    "orphan" when it is a Paused for an app whose previous Resumed / Paused was
    not a Resumed (the app was paused without having started). After long
    silences orphans are mostly Settings and home screens and usually sit next
    to a logged boot: the device restarted and the boot markers may be missing.
    after_silence_boot: a Device Startup or User Unlocked lies between the end
    of the silence and that event.

Usage
    python -m eyes_review.ingest <group_dir> [--db PATH] [--workers 3] [--limit N]
"""
import argparse
import glob
import os
import sqlite3
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
import pandas as pd

from eyeslib.core.event_classes import canonical_name, classify_series

GAP_SECONDS = 3 * 3600
IDLE_MIN_SECONDS = 10 * 60
IDLE_MIN_SHARE = 0.5
LONG_INFERRED_SECONDS = 2 * 3600
CONTEXT_SECONDS = 10 * 60
INFERRED_ENDS = {"screen_off", "shutdown", "end_of_log"}
BLOCK_TYPES = ["SHUTDOWN", "GAP", "IDLE", "GLANCE"]

SCHEMA = """
DROP TABLE IF EXISTS files;
DROP TABLE IF EXISTS blocks;
DROP TABLE IF EXISTS sessions;
DROP TABLE IF EXISTS session_apps;
DROP TABLE IF EXISTS app_usage;
DROP TABLE IF EXISTS events;
DROP TABLE IF EXISTS meta;
CREATE TABLE files (file_id INTEGER PRIMARY KEY, folder TEXT, raw_name TEXT, stem TEXT UNIQUE,
    participant TEXT, role TEXT, tz TEXT, first_t REAL, last_t REAL, n_events INTEGER,
    n_sessions INTEGER, session_h REAL, n_flagged INTEGER, gap_h REAL, idle_h REAL, car_h REAL);
CREATE TABLE blocks (file_id INTEGER, block_type TEXT, start REAL, end REAL);
CREATE TABLE sessions (sid INTEGER PRIMARY KEY, file_id INTEGER, session_id INTEGER,
    start REAL, end REAL, duration_s REAL, n_apps INTEGER, first_app TEXT, last_app TEXT,
    end_evidence TEXT, links_full INTEGER, links_inferred INTEGER, system_only INTEGER,
    longest_silence_s REAL, silence_start REAL, silence_end REAL,
    quiet_s REAL, quiet_start REAL, quiet_end REAL, hb_in_quiet INTEGER,
    n_usage INTEGER, n_state INTEGER, n_heartbeats INTEGER, last_usage_t REAL,
    gap_s REAL, idle_s REAL, shutdown_s REAL, glance_s REAL, reasons TEXT, flagged INTEGER, display TEXT,
    after_silence_t REAL, after_silence_app TEXT, after_silence_orphan INTEGER, after_silence_boot INTEGER);
CREATE TABLE session_apps (file_id INTEGER, session_id INTEGER, ord INTEGER, app TEXT, label TEXT,
    start REAL, end REAL, duration_s REAL, n_activities INTEGER, end_evidence TEXT,
    link TEXT, system_app INTEGER, display TEXT);
CREATE TABLE app_usage (file_id INTEGER, day TEXT, app TEXT, label TEXT, system_app INTEGER,
    seconds REAL, flagged_seconds REAL, display TEXT);
CREATE TABLE events (file_id INTEGER, t REAL, app TEXT, label TEXT, interaction_type TEXT, name TEXT, cls TEXT);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS verdicts (stem TEXT, start REAL, verdict TEXT, truncate_at REAL,
    latest_end REAL, note TEXT, reviewer TEXT, updated_at TEXT, PRIMARY KEY (stem, start));
"""

INDEXES = """
CREATE INDEX IF NOT EXISTS i_blocks ON blocks(file_id, start);
CREATE INDEX IF NOT EXISTS i_sessions_file ON sessions(file_id, session_id);
CREATE INDEX IF NOT EXISTS i_sessions_flag ON sessions(flagged, file_id);
CREATE INDEX IF NOT EXISTS i_apps ON session_apps(file_id, session_id);
CREATE INDEX IF NOT EXISTS i_usage ON app_usage(file_id, day);
CREATE INDEX IF NOT EXISTS i_events ON events(file_id, t);
"""


def secs(s):
    t = pd.to_datetime(s, utc=True, format="ISO8601", errors="coerce")
    return (t.dt.as_unit("ns").astype("int64") / 1e9).where(t.notna())


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


def covered(u, x):
    """Length of the union u (sorted, disjoint) that lies at or before each x."""
    x = np.asarray(x, dtype=float)
    if not len(u):
        return np.zeros_like(x)
    s, e = u[:, 0], u[:, 1]
    cum = np.concatenate([[0.0], np.cumsum(e - s)])
    k = np.searchsorted(s, x, "right")          # intervals starting at or before x
    j = np.maximum(k - 1, 0)
    part = np.clip(x - s[j], 0, e[j] - s[j])
    return np.where(k > 0, cum[j] + part, 0.0)


def split_by_day(apps, tz):
    """Split app periods at local midnight -> rows (day, app, label, system_app, seconds, session_id)."""
    rows = []
    for sid, app, label, sysapp, s, e, disp in zip(apps.session_id, apps.app_package_name, apps.app_label,
                                                  apps.system_app, apps.s, apps.e, apps.display):
        if not (e > s):
            continue
        cur = pd.Timestamp(s, unit="s", tz="UTC").tz_convert(tz)
        end = pd.Timestamp(e, unit="s", tz="UTC").tz_convert(tz)
        while cur < end:
            nxt = min(end, cur.normalize() + pd.DateOffset(days=1))
            rows.append((cur.strftime("%Y-%m-%d"), app, label, sysapp, (nxt - cur).total_seconds(), sid, disp))
            cur = nxt
    return rows


def load_file(folder, raw_path, file_id):
    t0 = time.time()
    name = os.path.basename(raw_path)
    stem = name[:-4].replace(" ", "_") + "_sorted_uniq_reordered"
    proc = os.path.join(folder, "processed")
    tok = name.split("_")
    participant = tok[0] + "_" + tok[1]
    role = "parent" if tok[1].startswith("P") else "child"

    ev = pd.read_csv(os.path.join(proc, stem + ".csv"), low_memory=False,
                     usecols=["app_package_name", "interaction_type", "event_timestamp", "application_label", "timezone"])
    ev["t"] = secs(ev["event_timestamp"])
    ev = ev.dropna(subset=["t"]).sort_values("t", kind="mergesort").reset_index(drop=True)
    tzs = ev["timezone"].dropna()
    tz = tzs.mode().iloc[0] if len(tzs) else "UTC"
    try:
        pd.Timestamp(0, unit="s", tz="UTC").tz_convert(tz)
    except Exception:
        tz = "UTC"
    t = ev["t"].to_numpy()
    ev["cls"] = classify_series(ev["interaction_type"])
    cls = ev["cls"].to_numpy()
    t_key = t[cls != "heartbeat"]          # usage + state events
    t_use = t[cls == "usage"]
    t_state = t[cls == "state"]
    t_hb = t[cls == "heartbeat"]

    blocks = pd.read_csv(os.path.join(proc, "segments", stem + "_BLOCKS.csv"))
    blocks["s"], blocks["e"] = secs(blocks["start_ts"]), secs(blocks["end_ts"])
    blocks = blocks.dropna(subset=["s", "e"])

    s = pd.read_csv(os.path.join(proc, "sessions", stem + "_SESSION.csv"))
    a = pd.read_csv(os.path.join(proc, "sessions", stem + "_SESSION_APPS.csv"))
    s["s"], s["e"] = secs(s["start_time"]), secs(s["end_time"])
    if "display" not in s:
        s["display"] = "phone"
    if "display" not in a:
        a["display"] = "phone"
    a["s"], a["e"] = secs(a["start_time"]), secs(a["end_time"])
    s = s.dropna(subset=["s", "e"]).reset_index(drop=True)
    st, en = s["s"].to_numpy(), s["e"].to_numpy()
    dur = (en - st)

    # longest stretch without any logged event inside each session
    i0 = np.searchsorted(t, st, "left")
    i1 = np.searchsorted(t, en, "right") - 1
    d = np.diff(t)
    sil = np.zeros(len(s))
    sil_a = np.full(len(s), np.nan)
    sil_b = np.full(len(s), np.nan)
    for k in np.where(i1 > i0)[0]:
        seg = d[i0[k]:i1[k]]
        j = int(seg.argmax())
        sil[k], sil_a[k], sil_b[k] = seg[j], t[i0[k] + j], t[i0[k] + j + 1]

    # heartbeat evidence (no thresholds): the longest stretch inside the session with no usage or
    # state event ("quiet"), how many heartbeats fall in it, and event counts by class
    n = len(s)
    q = np.zeros(n)
    q_a = np.full(n, np.nan)
    q_b = np.full(n, np.nan)
    k0 = np.searchsorted(t_key, st, "left")
    k1 = np.searchsorted(t_key, en, "right")
    for k in range(n):
        pts = np.r_[st[k], t_key[k0[k]:k1[k]], en[k]]
        dd = np.diff(pts)
        j = int(dd.argmax())
        q[k], q_a[k], q_b[k] = dd[j], pts[j], pts[j + 1]
    hb_in_quiet = np.searchsorted(t_hb, q_b, "left") - np.searchsorted(t_hb, q_a, "right")
    # boot signature: the first Resumed / Paused once the longest silence ends, and whether it is an orphan Paused
    nm = ev["interaction_type"].map(canonical_name)
    rp = ev[nm.isin(["Activity Resumed", "Activity Paused"])]
    rp_name = nm[rp.index]
    rp_prev = rp_name.groupby(rp["app_package_name"]).shift()
    rp_t = rp["t"].to_numpy()
    rp_orphan = ((rp_name == "Activity Paused") & (rp_prev != "Activity Resumed")).to_numpy()
    rp_app = rp["app_package_name"].to_numpy()
    t_boot = t[nm.isin(["Device Startup", "User Unlocked"]).to_numpy()]
    as_t = np.full(n, np.nan)
    as_app = np.full(n, None, dtype=object)
    as_orphan = np.zeros(n, dtype=int)
    as_boot = np.zeros(n, dtype=int)
    for k in np.where(~np.isnan(sil_b))[0]:
        j = int(np.searchsorted(rp_t, sil_b[k], "left"))
        if j < len(rp_t):
            as_t[k], as_app[k], as_orphan[k] = rp_t[j], rp_app[j], int(rp_orphan[j])
            as_boot[k] = int(np.searchsorted(t_boot, rp_t[j], "right") > np.searchsorted(t_boot, sil_b[k], "left"))

    count = lambda arr: np.searchsorted(arr, en, "right") - np.searchsorted(arr, st, "left")
    j = np.searchsorted(t_use, en, "right") - 1
    last_use = np.where(j >= 0, t_use[np.maximum(j, 0)] if len(t_use) else np.nan, np.nan)
    last_use = np.where(last_use >= st, last_use, np.nan)

    ov = {}
    for b in BLOCK_TYPES:
        u = union(blocks.loc[blocks["block_type"] == b, ["s", "e"]].to_numpy())
        ov[b] = covered(u, en) - covered(u, st)

    r_gap = sil >= GAP_SECONDS
    # screen off is expected for the car display (the phone is locked while it drives the car)
    r_idle = (ov["IDLE"] >= IDLE_MIN_SECONDS) & (ov["IDLE"] >= IDLE_MIN_SHARE * np.maximum(dur, 1e-9)) \
        & (s["display"].to_numpy() != "car")
    r_long = s["end_evidence"].isin(INFERRED_ENDS).to_numpy() & (dur >= LONG_INFERRED_SECONDS)
    reasons = [",".join(r for r, on in (("gap", g), ("idle", i), ("long_inferred", l)) if on)
               for g, i, l in zip(r_gap, r_idle, r_long)]
    flagged = r_gap | r_idle | r_long

    sessions = pd.DataFrame(dict(
        file_id=file_id, session_id=s["session_id"], start=st.round(3), end=en.round(3),
        duration_s=s["duration_s"], n_apps=s["n_apps"], first_app=s["first_app"], last_app=s["last_app"],
        end_evidence=s["end_evidence"], links_full=s["links_full"], links_inferred=s["links_inferred"],
        system_only=s["system_only"].astype(bool).astype(int),
        longest_silence_s=sil.round(3), silence_start=sil_a, silence_end=sil_b,
        quiet_s=q.round(3), quiet_start=q_a, quiet_end=q_b, hb_in_quiet=np.maximum(hb_in_quiet, 0),
        n_usage=count(t_use), n_state=count(t_state), n_heartbeats=count(t_hb), last_usage_t=last_use,
        gap_s=ov["GAP"], idle_s=ov["IDLE"], shutdown_s=ov["SHUTDOWN"], glance_s=ov["GLANCE"],
        reasons=reasons, flagged=flagged.astype(int), display=s["display"].fillna("phone"),
        after_silence_t=as_t, after_silence_app=as_app, after_silence_orphan=as_orphan,
        after_silence_boot=as_boot))

    apps = pd.DataFrame(dict(
        file_id=file_id, session_id=a["session_id"], ord=a["order"], app=a["app_package_name"],
        label=a["app_label"].fillna(""), start=a["s"], end=a["e"], duration_s=a["duration_s"],
        n_activities=a["n_activities"], end_evidence=a["end_evidence"],
        link=a["link_from_previous"].fillna(""), system_app=a["system_app"].astype(bool).astype(int),
        display=a["display"].fillna("phone")))

    # per-day app usage, with the part that belongs to flagged sessions
    a2 = a.dropna(subset=["s", "e"]).copy()
    a2["app_label"] = a2["app_label"].fillna("")
    a2["system_app"] = a2["system_app"].astype(bool).astype(int)
    parts = pd.DataFrame(split_by_day(a2, tz),
                         columns=["day", "app", "label", "system_app", "seconds", "session_id", "display"])
    fl = set(sessions.loc[sessions["flagged"] == 1, "session_id"])
    parts["flagged_seconds"] = np.where(parts["session_id"].isin(fl), parts["seconds"], 0.0)
    usage = (parts.groupby(["day", "app", "display"], as_index=False)
                  .agg(label=("label", "first"), system_app=("system_app", "first"),
                       seconds=("seconds", "sum"), flagged_seconds=("flagged_seconds", "sum")))
    usage.insert(0, "file_id", file_id)

    # raw events around flagged sessions
    win = union(np.c_[st[flagged] - CONTEXT_SECONDS, en[flagged] + CONTEXT_SECONDS])
    keep = np.zeros(len(t), dtype=bool)
    for w0, w1 in win:
        keep[np.searchsorted(t, w0, "left"):np.searchsorted(t, w1, "right")] = True
    events = pd.DataFrame(dict(file_id=file_id, t=t[keep], app=ev.loc[keep, "app_package_name"].to_numpy(),
                               label=ev.loc[keep, "application_label"].fillna("").to_numpy(),
                               interaction_type=ev.loc[keep, "interaction_type"].to_numpy(),
                               name=ev.loc[keep, "interaction_type"].map(canonical_name).to_numpy(),
                               cls=ev.loc[keep, "cls"].to_numpy()))

    blocks_out = pd.DataFrame(dict(file_id=file_id, block_type=blocks["block_type"], start=blocks["s"], end=blocks["e"]))

    frow = dict(file_id=file_id, folder=os.path.basename(folder), raw_name=name, stem=stem,
                participant=participant, role=role, tz=tz,
                first_t=float(t[0]) if len(t) else None, last_t=float(t[-1]) if len(t) else None,
                n_events=int(len(t)), n_sessions=int(len(s)), session_h=float(dur.sum() / 3600),
                n_flagged=int(flagged.sum()),
                gap_h=float(blocks.loc[blocks.block_type == "GAP", "duration_seconds"].sum() / 3600),
                idle_h=float(blocks.loc[blocks.block_type == "IDLE", "duration_seconds"].sum() / 3600),
                car_h=float(a.loc[a["display"] == "car", "duration_s"].sum() / 3600))
    return dict(file=pd.DataFrame([frow]), blocks=blocks_out, sessions=sessions, session_apps=apps,
                app_usage=usage, events=events, secs=time.time() - t0,
                counts=dict(gap=int(r_gap.sum()), idle=int(r_idle.sum()), long_inferred=int(r_long.sum())))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("group_dir")
    ap.add_argument("--db")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    group = os.path.abspath(os.path.expanduser(a.group_dir))
    db = a.db or os.path.join(group, "_review", "eyes_review.sqlite")
    os.makedirs(os.path.dirname(db), exist_ok=True)

    tasks = []
    for folder in sorted(glob.glob(os.path.join(group, "*"))):
        if os.path.isdir(folder) and not os.path.basename(folder).startswith("_"):
            tasks += [(folder, raw) for raw in sorted(glob.glob(os.path.join(folder, "*.csv")))]
    if a.limit:
        tasks = tasks[:a.limit]

    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    if "latest_end" not in [c[1] for c in con.execute("PRAGMA table_info(verdicts)")]:
        con.execute("ALTER TABLE verdicts ADD COLUMN latest_end REAL")
    con.executemany("INSERT INTO meta VALUES (?, ?)", [
        ("group_dir", group), ("ingested_at", time.strftime("%Y-%m-%d %H:%M:%S")),
        ("GAP_SECONDS", str(GAP_SECONDS)), ("IDLE_MIN_SECONDS", str(IDLE_MIN_SECONDS)),
        ("IDLE_MIN_SHARE", str(IDLE_MIN_SHARE)), ("LONG_INFERRED_SECONDS", str(LONG_INFERRED_SECONDS)),
        ("CONTEXT_SECONDS", str(CONTEXT_SECONDS))])
    con.commit()

    t_start = time.time()
    done, errors = 0, []
    tot = dict(gap=0, idle=0, long_inferred=0, flagged=0, sessions=0)
    with ProcessPoolExecutor(a.workers) as ex:
        futs = {ex.submit(load_file, f, r, i): r for i, (f, r) in enumerate(tasks, 1)}
        for fut in as_completed(futs):
            raw = os.path.basename(futs[fut])
            done += 1
            try:
                res = fut.result()
            except Exception as e:  # keep going, report at the end
                errors.append((raw, repr(e)))
                print(f"[{done}/{len(tasks)}] ERROR {raw[:40]}: {e!r}", flush=True)
                continue
            res["file"].to_sql("files", con, if_exists="append", index=False)
            for tbl in ["blocks", "sessions", "session_apps", "app_usage", "events"]:
                res[tbl].to_sql(tbl, con, if_exists="append", index=False)
            con.commit()
            for k, v in res["counts"].items():
                tot[k] += v
            tot["flagged"] += int(res["sessions"]["flagged"].sum())
            tot["sessions"] += len(res["sessions"])
            print(f"[{done}/{len(tasks)}] {raw[:40]:40s} {len(res['sessions']):6d} sessions "
                  f"{int(res['sessions']['flagged'].sum()):4d} flagged {res['secs']:5.1f}s", flush=True)
    con.executescript(INDEXES)
    con.commit()
    con.close()
    print(f"sessions {tot['sessions']}, flagged {tot['flagged']} "
          f"(gap {tot['gap']}, idle {tot['idle']}, long_inferred {tot['long_inferred']}); "
          f"errors {len(errors)}; {time.time() - t_start:.0f}s -> {db}")
    for r, e in errors:
        print("ERROR", r, e)
    print("ALL_DONE")


if __name__ == "__main__":
    main()
