"""
Load device-state results (eyeslib.states.device_state, processed/states/*_STATES.csv)
into the review database, for the "Device state review" tab.

Tables (rebuilt each time)
    state_files   hours per file, layer (strict / likely) and label
    state_days    the same per local day (split at local midnight)
    state_rules   hours per file, layer, rule and label
Tables kept across rebuilds (the reviewer's work)
    state_file_review   per file: status (ok / problem), note
    state_rulings       per interval: the label the reviewer rules, note

Run python -m eyes_review.ingest first (it creates the files table).
Usage: python -m eyes_review.ingest_states [--db PATH]
"""
import argparse
import os
import sqlite3
import time

import numpy as np
import pandas as pd

from eyeslib.states.device_state import LABEL_ORDER, TOLERANCE_SECONDS

SCHEMA = """
DROP TABLE IF EXISTS state_files;
DROP TABLE IF EXISTS state_days;
DROP TABLE IF EXISTS state_rules;
CREATE TABLE state_files (file_id INTEGER, layer TEXT, label TEXT, hours REAL);
CREATE TABLE state_days (file_id INTEGER, day TEXT, layer TEXT, label TEXT, hours REAL);
CREATE TABLE state_rules (file_id INTEGER, layer TEXT, rule TEXT, label TEXT, hours REAL, n INTEGER);
DROP TABLE IF EXISTS state_block_counts;
DROP TABLE IF EXISTS state_blocks;
CREATE TABLE state_block_counts (file_id INTEGER, layer TEXT, label TEXT, n INTEGER, hours REAL);
CREATE TABLE state_blocks (block_id INTEGER PRIMARY KEY, file_id INTEGER, layer TEXT, block_no INTEGER,
    start REAL, end REAL, duration_s REAL, label TEXT, rules TEXT, n_events INTEGER,
    left_event TEXT, left_app TEXT, right_event TEXT, right_app TEXT, reason TEXT,
    off_sign TEXT, on_sign TEXT, boot_score REAL, app TEXT);
DROP TABLE IF EXISTS state_signs;
CREATE TABLE state_signs (file_id INTEGER, verdict TEXT, how TEXT, n INTEGER, hours REAL, signature TEXT);
CREATE TABLE IF NOT EXISTS state_file_review (stem TEXT PRIMARY KEY, status TEXT, note TEXT, reviewer TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS state_rulings (stem TEXT, start REAL, end REAL, label TEXT, note TEXT, reviewer TEXT,
    updated_at TEXT, PRIMARY KEY (stem, start));
CREATE INDEX IF NOT EXISTS i_state_days ON state_days(file_id, day);
"""
INDEXES = """
CREATE INDEX IF NOT EXISTS i_state_blocks ON state_blocks(layer, duration_s);
CREATE INDEX IF NOT EXISTS i_state_blocks_file ON state_blocks(file_id, layer, start);
"""
CONFIRMED = {"Off", "Idle", "Active", "No logging", "No logging, likely off"}
# The review list holds QUIET STRETCHES, not blocks: each is one gap between two consecutive events (no event
# inside) of at least the tolerance whose state is unsure (processed/states/<stem>_QUIET.csv). A ruling then covers
# exactly the silence. (A block can contain events, e.g. heartbeats at its end that prove the device was on.)
# The table keeps its name state_blocks; block_no is the stretch number (its interval index in the file).


def blocks(s, layer):
    """Merge consecutive intervals with the same label (in one layer) into blocks.
    Returns a DataFrame: block_no, start, end, duration_s, label, rules, n_events."""
    lab = s[layer].to_numpy()
    first = np.r_[True, lab[1:] != lab[:-1]]
    bno = np.cumsum(first)                       # 1-based block number of every interval
    st = np.where(first)[0]
    en = np.r_[st[1:], len(s)] - 1
    nrows = en - st + 1
    n_ev = np.add.reduceat(s["n_events"].to_numpy(), st) - (nrows - 1)
    b = pd.DataFrame(dict(block_no=np.arange(1, len(st) + 1), start=s["start"].to_numpy()[st],
                          end=s["end"].to_numpy()[en], label=lab[st], n_events=n_ev))
    b["duration_s"] = b["end"] - b["start"]
    return b, bno


def rule_mix(s, layer, bno, keep):
    """'rule 12.3 h; rule 0.4 h' for the blocks in keep (block numbers)."""
    m = np.isin(bno, keep)
    if not m.any():
        return {}
    g = (pd.DataFrame(dict(b=bno[m], r=s[f"rule_{layer}"].to_numpy()[m], d=s["duration_s"].to_numpy()[m]))
         .groupby(["b", "r"])["d"].sum().reset_index().sort_values(["b", "d"], ascending=[True, False]))
    return {k: "; ".join(f"{r} {d / 3600:.2f} h" for r, d in zip(x["r"], x["d"])) for k, x in g.groupby("b")}


def states_path(group_dir, folder, stem):
    return os.path.join(group_dir, folder, "processed", "states", stem + "_STATES.csv")


def per_day(s, layer, tz):
    """Hours per local day and label; intervals are disjoint and sorted."""
    t0, t1 = s["start"].min(), s["end"].max()
    # local midnights on the calendar (not 24 h steps, which drift across DST changes)
    d0 = pd.Timestamp(t0, unit="s", tz="UTC").tz_convert(tz).tz_localize(None).normalize()
    d1 = pd.Timestamp(t1, unit="s", tz="UTC").tz_convert(tz).tz_localize(None).normalize() + pd.DateOffset(days=1)
    days = pd.date_range(d0, d1, freq="D").tz_localize(tz, ambiguous="NaT", nonexistent="shift_forward")
    edges = days.tz_convert("UTC").as_unit("ns").asi8 / 1e9
    out = []
    for lab, g in s.groupby(layer):
        st, en = g["start"].to_numpy(), g["end"].to_numpy()
        cum = np.r_[0.0, np.cumsum(en - st)]

        def covered(x):
            i = np.searchsorted(st, x, "right") - 1
            part = np.where(i >= 0, np.minimum(x, en[np.maximum(i, 0)]) - st[np.maximum(i, 0)], 0.0)
            return cum[np.maximum(i, 0)] * (i >= 0) + np.maximum(part, 0.0)
        h = np.diff(covered(edges)) / 3600
        for day, hours in zip(days[:-1].strftime("%Y-%m-%d"), h):
            if hours > 0:
                out.append((day, layer, lab, float(hours)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.expanduser("~/workspace/screen_time/by_group/A1/_review/eyes_review.sqlite"))
    a = ap.parse_args()
    con = sqlite3.connect(a.db)
    con.executescript(SCHEMA)
    group = con.execute("SELECT value FROM meta WHERE key = 'group_dir'").fetchone()[0]
    files = con.execute("SELECT file_id, folder, stem, tz FROM files ORDER BY file_id").fetchall()
    t_start = time.time()
    missing = []
    for k, (fid, folder, stem, tz) in enumerate(files, 1):
        p = states_path(group, folder, stem)
        if not os.path.exists(p):
            missing.append(stem)
            continue
        s = pd.read_csv(p)
        if s.empty:
            continue
        qp = p.replace("_STATES.csv", "_QUIET.csv")
        quiet = pd.read_csv(qp) if os.path.exists(qp) else pd.DataFrame()
        for layer in ("strict", "likely"):
            h = s.groupby(layer)["duration_s"].sum() / 3600
            con.executemany("INSERT INTO state_files VALUES (?, ?, ?, ?)",
                            [(fid, layer, lab, float(h.get(lab, 0.0))) for lab in LABEL_ORDER])
            r = s.groupby([f"rule_{layer}", layer])["duration_s"].agg(["sum", "size"]).reset_index()
            con.executemany("INSERT INTO state_rules VALUES (?, ?, ?, ?, ?, ?)",
                            [(fid, layer, x[0], x[1], float(x[2]) / 3600, int(x[3])) for x in r.itertuples(index=False)])
            con.executemany("INSERT INTO state_days VALUES (?, ?, ?, ?, ?)",
                            [(fid,) + row for row in per_day(s, layer, tz)])
            b, bno = blocks(s, layer)
            c = b.groupby("label")["duration_s"].agg(["size", "sum"])
            con.executemany("INSERT INTO state_block_counts VALUES (?, ?, ?, ?, ?)",
                            [(fid, layer, lab, int(c.loc[lab, "size"]) if lab in c.index else 0,
                              float(c.loc[lab, "sum"]) / 3600 if lab in c.index else 0.0) for lab in LABEL_ORDER])
            if len(quiet):
                # this layer's review list: unsure in the layer, conflicts and long On stretches (both layers),
                # and long continuity-only stretches (strict layer, where continuity decides)
                uns = ~quiet[layer].isin(CONFIRMED)
                extra = quiet["reason"].isin(["conflict", "long_off_check", "no_logging", "app_usage"] + (["continuity_check"] if layer == "strict" else []))
                u = quiet[uns | extra]
                why = np.where(u["reason"] == "conflict", "conflict", np.where(~u[layer].isin(CONFIRMED), "unsure", u["reason"]))
                txt = lambda v: "" if pd.isna(v) else str(v)
                con.executemany("""INSERT INTO state_blocks (file_id, layer, block_no, start, end, duration_s, label, rules,
                    n_events, left_event, left_app, right_event, right_app, reason, off_sign, on_sign, boot_score, app)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 2, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                [(fid, layer, int(r.stretch_no), float(r.start), float(r.end), float(r.duration_s),
                                  getattr(r, layer), getattr(r, f"rule_{layer}"), r.left_event, str(r.left_app),
                                  r.right_event, str(r.right_app), w, txt(r.off_sign), txt(r.on_sign),
                                  None if pd.isna(r.boot_score) else float(r.boot_score), txt(getattr(r, "app", "")))
                                 for r, w in zip(u.itertuples(index=False), why)])
        pp = p.replace("_STATES.csv", "_PROFILE.csv")            # incomplete car-screen sessions: a review list of their own
        if os.path.exists(pp):
            pf = pd.read_csv(pp, keep_default_na=False)
            ci = pf[pf["kind"] == "car_incomplete"]
            for layer in ("strict", "likely"):
                con.executemany("""INSERT INTO state_blocks (file_id, layer, block_no, start, end, duration_s, label, rules,
                    n_events, left_event, left_app, right_event, right_app, reason, off_sign, on_sign, boot_score, app)
                    VALUES (?, ?, ?, ?, ?, ?, 'Car session?', ?, 2, '', '', '', '', 'car_review', '', '', NULL, ?)""",
                                [(fid, layer, i, float(r.start) + 0.005, float(r.end), float(r.duration_s), r.flag, r.flag)
                                 for i, r in enumerate(ci.itertuples(index=False), 1)])   # +5 ms: its ruling never lands on a quiet stretch
            # small-window / panel periods to review (reviewer, 2026-10-03: any suspicious one, long silent ones included):
            # graded likely (cut at a screen-off, or a silence of 5 min or more inside), or a panel open 5 min or more
            if "grade" in pf.columns:
                pv = pf[pf["kind"].isin(["pip", "pip_back", "pip_wake", "cover"])]
                pv = pv[(pv["grade"] == "likely") | ((pv["kind"] == "cover") & (pv["duration_s"].astype(float) >= 300))]
                def why(r):
                    w = "end not logged: cut at a screen-off" if r.flag == "cut at screen-off" else \
                        "length is within this file's slow-Stopped tail (1 in 100 ordinary Stoppeds is this late)" \
                        if r.flag == "near the file's Stopped delay" else "panel open 5 min or more" \
                        if r.kind == "cover" and r.grade != "likely" else "silence of 5 min or more inside"
                    how = {"pip": "ended by closing", "pip_back": "ended by returning to the app",
                           "pip_wake": "came back at screen-on", "cover": "covered by a panel"}[r.kind]
                    return f"{how}; {w}" + ("" if r.flag in ("", "cut at screen-off", "near the file's Stopped delay") else f"; in front: {r.flag}")
                for layer in ("strict", "likely"):
                    con.executemany("""INSERT INTO state_blocks (file_id, layer, block_no, start, end, duration_s, label, rules,
                        n_events, left_event, left_app, right_event, right_app, reason, off_sign, on_sign, boot_score, app)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 2, '', '', '', '', 'pip_review', '', '', NULL, ?)""",
                                    [(fid, layer, 100000 + i, float(r.start) + 0.007, float(r.end), float(r.duration_s),
                                      "Covered?" if r.kind == "cover" else "Small window?", why(r), r.app)
                                     for i, r in enumerate(pv.itertuples(index=False), 1)])
        bp = p.replace("_STATES.csv", "_STORY_BREAKS.csv")         # app-level story breaks (story checker, 10-10)
        if os.path.exists(bp):
            sb = pd.read_csv(bp, keep_default_na=False)
            for layer in ("strict", "likely"):
                con.executemany("""INSERT INTO state_blocks (file_id, layer, block_no, start, end, duration_s, label, rules,
                    n_events, left_event, left_app, right_event, right_app, reason, off_sign, on_sign, boot_score, app)
                    VALUES (?, ?, ?, ?, ?, 1.0, ?, ?, 2, '', '', '', '', 'story_break', '', '', NULL, ?)""",
                                [(fid, layer, 200000 + i, float(r.t) + 0.003, float(r.t) + 1.003, "Story break",
                                  f"{r.kind}|{r.context}|{r.front}", r.app) for i, r in enumerate(sb.itertuples(index=False), 1)])
        sp = p.replace("_STATES.csv", "_SIGNS.csv")
        if os.path.exists(sp) and os.path.getsize(sp) > 40:
            sg = pd.read_csv(sp)
            sg["how"] = sg["how"].fillna("")
            g = sg.groupby(["verdict", "how"])["duration_s"].agg(["size", "sum"]).reset_index()
            con.executemany("INSERT INTO state_signs VALUES (?, ?, ?, ?, ?, ?)",
                            [(fid, x[0], x[1], int(x[2]), float(x[3]) / 3600, str(sg["signature"].iat[0]))
                             for x in g.itertuples(index=False)])
        con.commit()
        print(f"[{k}/{len(files)}] {stem[:40]} {len(s)} intervals", flush=True)
    con.executescript(INDEXES)
    # rulings saved on a block keep their start; end them where the quiet stretch starting there ends
    con.execute("""UPDATE state_rulings SET end = (SELECT MIN(b.end) FROM state_blocks b JOIN files f ON f.file_id = b.file_id
        WHERE f.stem = state_rulings.stem AND abs(b.start - state_rulings.start) < 0.001)
        WHERE EXISTS (SELECT 1 FROM state_blocks b JOIN files f ON f.file_id = b.file_id
        WHERE f.stem = state_rulings.stem AND abs(b.start - state_rulings.start) < 0.001)""")
    con.commit()
    con.close()
    print(f"done in {time.time() - t_start:.0f}s; missing {len(missing)}")
    for m in missing:
        print("MISSING", m)
    print("ALL_DONE")


if __name__ == "__main__":
    main()
