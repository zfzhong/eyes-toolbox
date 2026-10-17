"""
Local review app for flagged sessions.

Usage
    python -m eyes_review.server [--db PATH] [--port 8877]
then open http://127.0.0.1:8877

Only listens on 127.0.0.1: the data never leaves this computer.
"""
import argparse
import csv
import datetime
import getpass
import glob
import io
import json
import os
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd

from eyeslib.core.event_classes import canonical_name, event_class
from eyeslib.states.device_state import LABEL_ORDER

# ---------- device states: per-file tables are read on demand and kept in a small cache
_CACHE, _LOCK, CACHE_SIZE = {}, threading.Lock(), 6
STATE_LABELS = set(LABEL_ORDER) | {"Car session", "Not a car session", "Car unsure", "Small window", "Covered by a panel", "Not visible", "PiP unsure",
                                  "Lost event", "Two apps in front", "Car projection", "Screen / lock", "New story", "Log error", "Story unsure"}   # the last three: car-session review
MAX_INTERVALS = 20000


def cached(key, loader):
    with _LOCK:
        if key in _CACHE:
            _CACHE[key] = _CACHE.pop(key)
            return _CACHE[key]
    val = loader()
    with _LOCK:
        _CACHE[key] = val
        while len(_CACHE) > CACHE_SIZE:
            _CACHE.pop(next(iter(_CACHE)))
    return val


def load_raw_events(path):
    df = pd.read_csv(path, usecols=lambda c: c in {"app_package_name", "interaction_type", "event_timestamp",
                                                   "application_label"}, low_memory=False)
    ts = pd.to_datetime(df["event_timestamp"], utc=True, format="ISO8601", errors="coerce")
    df["t"] = ts.dt.as_unit("ns").astype("int64") / 1e9
    df = df[ts.notna()].sort_values("t", kind="mergesort").reset_index(drop=True)
    names = {v: canonical_name(v) for v in df["interaction_type"].unique()}
    df["name"] = df["interaction_type"].map(names)
    df["cls"] = df["name"].map({v: event_class(v) for v in set(names.values())})
    if "application_label" not in df:
        df["application_label"] = ""
    df["application_label"] = df["application_label"].fillna("")
    df["app_package_name"] = df["app_package_name"].fillna("")
    return df[["t", "app_package_name", "application_label", "interaction_type", "name", "cls"]]

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
SCENARIOS_MD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "scenarios.md")
PROBLEM = "- **Problem it illustrates:**"
# State-chain review (David, 10-16): <A1>/<category>/_review/state_review.json, built by A1/_review/state_review_build.py
STATE_DIR = os.environ.get("EYES_A1_DIR", os.path.expanduser("~/workspace/screen_time/A1"))
STATE_VERDICTS = {"screen-off lost", "screen-on lost", "hidden power cycle", "duplicate screen event", "logging gap", "other", "unsure",
                  # app-chain failures inside device-state blocks (block_review.json, 10-16)
                  "Paused lost", "Resumed lost", "Stopped lost", "kill", "app over lock screen", "background launch", "duplicate event",
                  "device-specific", "long use", "logging gap: screen-off and screen-on lost", "power cycle lost"}


def load_scenarios(path=SCENARIOS_MD):
    """docs/scenarios.md (a copy of the project's representative scenarios) split into the intro and one entry
    per "## S<n>." heading. Each entry's "Problem it illustrates" bullet becomes its summary."""
    import re
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    intro, items, cur = [], [], None
    for ln in lines:
        m = re.match(r"^## (S\d+)\.\s*(.*)$", ln)
        if m:
            cur = {"id": m.group(1), "title": m.group(2).strip(), "problem": "", "body": []}
            items.append(cur)
        elif cur is None:
            intro.append(ln)
        elif ln.startswith(PROBLEM):
            cur["problem"] = ln[len(PROBLEM):].strip()
        else:
            cur["body"].append(ln)
    for it in items:
        while it["body"] and it["body"][-1].strip() in ("", "---"):
            it["body"].pop()
        it["body"] = "\n".join(it["body"]).strip("\n")
    while intro and intro[-1].strip() in ("", "---"):
        intro.pop()
    return {"intro": "\n".join(intro), "scenarios": items}
VERDICTS = {"keep", "truncate", "log_missing", "exclude", "unsure"}
CUT_VERDICTS = {"truncate", "log_missing"}   # verdicts that end the session at truncate_at
MAX_EVENTS = 4000

SESSION_COLS = """s.sid, s.file_id, s.session_id, s.start, s.end, s.duration_s, s.n_apps, s.first_app,
    s.last_app, s.end_evidence, s.links_full, s.links_inferred, s.system_only, s.longest_silence_s,
    s.silence_start, s.silence_end, s.quiet_s, s.quiet_start, s.quiet_end, s.hb_in_quiet, s.n_usage,
    s.n_state, s.n_heartbeats, s.last_usage_t, s.display, s.gap_s, s.idle_s, s.shutdown_s, s.glance_s, s.reasons, s.flagged,
    s.after_silence_t, s.after_silence_app, s.after_silence_orphan, s.after_silence_boot,
    f.participant, f.role, f.tz, f.folder, f.stem, v.verdict, v.truncate_at, v.latest_end, v.note, v.reviewer, v.updated_at"""
SESSION_FROM = """sessions s JOIN files f ON f.file_id = s.file_id
    LEFT JOIN verdicts v ON v.stem = f.stem AND v.start = s.start"""


def rows(cur):
    return [dict(r) for r in cur.fetchall()]


class Handler(BaseHTTPRequestHandler):
    db_path = None

    # ---------- plumbing
    def db(self):
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    def send(self, body, ctype="application/json", code=200, extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        p = u.path.rstrip("/") or "/"
        try:
            if p == "/":
                with open(os.path.join(STATIC, "index.html"), "rb") as f:
                    return self.send(f.read(), "text/html; charset=utf-8")
            if p == "/api/summary":
                return self.send(self.summary())
            if p == "/api/queue":
                return self.send(self.queue(q))
            if p.startswith("/api/session/"):
                return self.send(self.session(int(p.rsplit("/", 1)[1])))
            if p == "/api/files":
                return self.send(self.files())
            if p.startswith("/api/file/"):
                return self.send(self.file_usage(int(p.rsplit("/", 1)[1])))
            if p == "/api/export/sessions.csv":
                return self.export(q)
            if p == "/api/states/files":
                return self.send(self.state_files())
            if p.startswith("/api/states/file/"):
                return self.send(self.state_file(int(p.rsplit("/", 1)[1])))
            if p.startswith("/api/states/strip/"):
                return self.send(self.state_strip(int(p.rsplit("/", 1)[1]), q.get("layer", "likely")))
            if p == "/api/states/summary":
                return self.send(self.state_summary(q))
            if p.startswith("/api/states/profile/"):
                return self.send(self.state_profile(int(p.rsplit("/", 1)[1]), float(q["t0"]), float(q["t1"])))
            if p == "/api/states/review_files":
                return self.send(self.state_review_files(q))
            if p == "/api/states/blocks":
                return self.send(self.state_blocks(q))
            if p.startswith("/api/states/block/"):
                return self.send(self.state_block(int(p.rsplit("/", 1)[1]), int(q.get("context", 150))))
            if p.startswith("/api/states/events/"):
                return self.send(self.state_events(int(p.rsplit("/", 1)[1]), int(q["i0"]), int(q["i1"])))
            if p == "/api/state_review":
                return self.send(self.state_review_items())
            if p == "/api/block_nbr":
                return self.send(self.block_nbr(q))
            if p == "/api/scenarios":
                return self.send(self.scenarios())
            if p.startswith("/api/states/window/"):
                return self.send(self.state_window(int(p.rsplit("/", 1)[1]), float(q["t0"]), float(q["t1"])))
            return self.send({"error": "not found"}, code=404)
        except Exception as e:  # show the error in the UI instead of a dead page
            return self.send({"error": repr(e)}, code=500)

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            path = urlparse(self.path).path
            if path == "/api/verdict":
                return self.send(self.verdict(body))
            if path == "/api/states/review":
                return self.send(self.state_review(body))
            if path == "/api/states/ruling":
                return self.send(self.state_ruling(body))
            if path == "/api/states/rulings_bulk":
                return self.send(self.state_rulings_bulk(body))
            if path == "/api/state_review_save":
                return self.send(self.state_review_save(body))
            if path == "/api/scenario_comment":
                return self.send(self.scenario_comment(body))
            return self.send({"error": "not found"}, code=404)
        except Exception as e:
            return self.send({"error": repr(e)}, code=500)

    # ---------- API
    def summary(self):
        con = self.db()
        meta = {r["key"]: r["value"] for r in con.execute("SELECT key, value FROM meta")}
        tot = dict(con.execute("""SELECT COUNT(*) AS sessions, SUM(duration_s)/3600.0 AS session_h,
            SUM(flagged) AS flagged, SUM(CASE WHEN flagged=1 THEN duration_s ELSE 0 END)/3600.0 AS flagged_h
            FROM sessions""").fetchone())
        tot["files"] = con.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        car = con.execute("SELECT COUNT(*), COALESCE(SUM(duration_s), 0) / 3600.0, COUNT(DISTINCT file_id) "
                          "FROM sessions WHERE display = 'car'").fetchone()
        tot["car_sessions"], tot["car_h"], tot["car_files"] = car[0], car[1], car[2]
        by_reason = {}
        for r in ["gap", "idle", "long_inferred"]:
            by_reason[r] = con.execute("SELECT COUNT(*) FROM sessions WHERE reasons LIKE ?", (f"%{r}%",)).fetchone()[0]
        by_role = rows(con.execute(f"""SELECT f.role, COUNT(*) AS sessions, SUM(s.flagged) AS flagged,
            SUM(CASE WHEN v.verdict IS NOT NULL AND s.flagged=1 THEN 1 ELSE 0 END) AS reviewed
            FROM {SESSION_FROM} GROUP BY f.role"""))
        verdicts = rows(con.execute(f"""SELECT v.verdict, COUNT(*) AS n FROM {SESSION_FROM}
            WHERE s.flagged=1 AND v.verdict IS NOT NULL GROUP BY v.verdict"""))
        return dict(meta=meta, total=tot, by_reason=by_reason, by_role=by_role, verdicts=verdicts)

    def queue(self, q):
        where, args = ["s.flagged = 1"], []
        if q.get("reason") and q["reason"] != "all":
            where.append("s.reasons LIKE ?")
            args.append(f"%{q['reason']}%")
        if q.get("role") in ("parent", "child"):
            where.append("f.role = ?")
            args.append(q["role"])
        if q.get("status") == "todo":
            where.append("v.verdict IS NULL")
        elif q.get("status") == "done":
            where.append("v.verdict IS NOT NULL")
        if q.get("file_id"):
            where.append("s.file_id = ?")
            args.append(int(q["file_id"]))
        order = {"duration": "s.duration_s DESC", "silence": "s.quiet_s DESC",
                 "file": "f.participant, s.start"}.get(q.get("sort"), "s.duration_s DESC")
        sql = f"""SELECT s.sid, s.start, s.duration_s, s.longest_silence_s, s.quiet_s, s.hb_in_quiet, s.idle_s, s.reasons, s.n_apps,
            s.first_app, s.display, f.participant, f.role, f.tz, f.folder, v.verdict
            FROM {SESSION_FROM} WHERE {' AND '.join(where)} ORDER BY {order} LIMIT 2000"""
        return rows(self.db().execute(sql, args))

    def session(self, sid):
        con = self.db()
        r = con.execute(f"SELECT {SESSION_COLS} FROM {SESSION_FROM} WHERE s.sid = ?", (sid,)).fetchone()
        if r is None:
            return {"error": "no such session"}
        s = dict(r)
        pad = min(600.0, max(60.0, 0.05 * s["duration_s"]))
        w0, w1 = s["start"] - pad, s["end"] + pad
        apps = rows(con.execute("""SELECT ord, app, label, start, end, duration_s, n_activities, end_evidence,
            link, system_app FROM session_apps WHERE file_id = ? AND session_id = ? ORDER BY ord""",
                                (s["file_id"], s["session_id"])))
        blocks = rows(con.execute("""SELECT block_type, start, end FROM blocks
            WHERE file_id = ? AND end > ? AND start < ? ORDER BY start""", (s["file_id"], w0, w1)))
        n_ev = con.execute("SELECT COUNT(*) FROM events WHERE file_id = ? AND t BETWEEN ? AND ?",
                           (s["file_id"], w0, w1)).fetchone()[0]
        events = rows(con.execute("""SELECT t, app, label, interaction_type, name, cls FROM events
            WHERE file_id = ? AND t BETWEEN ? AND ? ORDER BY t LIMIT ?""", (s["file_id"], w0, w1, MAX_EVENTS)))
        near = rows(con.execute("""SELECT sid, session_id, start, end, first_app FROM sessions
            WHERE file_id = ? AND end > ? AND start < ? AND sid != ? ORDER BY start""",
                                (s["file_id"], w0, w1, sid)))
        return dict(session=s, window=[w0, w1], apps=apps, blocks=blocks, events=events,
                    events_total=n_ev, neighbours=near)

    def verdict(self, b):
        con = self.db()
        r = con.execute("SELECT f.stem, s.file_id, s.start, s.end FROM sessions s JOIN files f ON f.file_id = s.file_id "
                        "WHERE s.sid = ?", (int(b["sid"]),)).fetchone()
        if r is None:
            return {"error": "no such session"}
        v = b.get("verdict")
        if not v:
            con.execute("DELETE FROM verdicts WHERE stem = ? AND start = ?", (r["stem"], r["start"]))
        else:
            if v not in VERDICTS:
                return {"error": f"unknown verdict {v}"}
            ta = b.get("truncate_at")
            latest = None
            if v in CUT_VERDICTS:
                if ta is None or not (r["start"] < float(ta) <= r["end"]):
                    return {"error": "the cut point must fall inside the session"}
                ta = float(ta)
                if v == "log_missing":
                    # the log is missing after the cut; the session ended no later than the next
                    # event the log did record (or the session's own end, if that is earlier)
                    nxt = con.execute("SELECT MIN(t) FROM events WHERE file_id = ? AND t > ?",
                                      (r["file_id"], ta)).fetchone()[0]
                    latest = min(nxt, r["end"]) if nxt is not None else r["end"]
            else:
                ta = None
            con.execute("""INSERT INTO verdicts (stem, start, verdict, truncate_at, latest_end, note, reviewer, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(stem, start) DO UPDATE SET verdict=excluded.verdict,
                truncate_at=excluded.truncate_at, latest_end=excluded.latest_end, note=excluded.note,
                reviewer=excluded.reviewer, updated_at=excluded.updated_at""",
                        (r["stem"], r["start"], v, ta, latest, b.get("note") or "",
                         getpass.getuser(), datetime.datetime.now().isoformat(timespec="seconds")))
        con.commit()
        return {"ok": True}

    def files(self):
        return rows(self.db().execute(f"""SELECT f.file_id, f.folder, f.participant, f.role, f.tz, f.first_t,
            f.last_t, f.n_events, f.n_sessions, f.session_h, f.n_flagged, f.gap_h, f.idle_h, f.car_h,
            (SELECT COUNT(*) FROM sessions s JOIN verdicts v ON v.stem = f.stem AND v.start = s.start
               WHERE s.file_id = f.file_id AND s.flagged = 1) AS n_reviewed,
            (SELECT group_concat(verdict || ':' || n, ',') FROM (
               SELECT v.verdict, COUNT(*) AS n FROM sessions s JOIN verdicts v ON v.stem = f.stem AND v.start = s.start
               WHERE s.file_id = f.file_id AND s.flagged = 1 GROUP BY v.verdict)) AS verdict_counts
            FROM files f ORDER BY f.participant, f.folder"""))

    def file_usage(self, file_id):
        con = self.db()
        f = dict(con.execute("SELECT * FROM files WHERE file_id = ?", (file_id,)).fetchone())
        days = rows(con.execute("""SELECT day, SUM(CASE WHEN display='car' THEN 0 ELSE seconds END)/3600.0 AS hours,
            SUM(CASE WHEN display='car' THEN 0 ELSE flagged_seconds END)/3600.0 AS flagged_h,
            SUM(CASE WHEN display='car' THEN seconds ELSE 0 END)/3600.0 AS car_h,
            SUM(CASE WHEN system_app=1 THEN seconds ELSE 0 END)/3600.0 AS system_h
            FROM app_usage WHERE file_id = ? GROUP BY day ORDER BY day""", (file_id,)))
        top = rows(con.execute("""SELECT app, MAX(label) AS label, MAX(system_app) AS system_app,
            SUM(CASE WHEN display='car' THEN 0 ELSE seconds END)/3600.0 AS hours,
            SUM(CASE WHEN display='car' THEN 0 ELSE flagged_seconds END)/3600.0 AS flagged_h,
            SUM(CASE WHEN display='car' THEN seconds ELSE 0 END)/3600.0 AS car_h, COUNT(DISTINCT day) AS days
            FROM app_usage WHERE file_id = ? GROUP BY app ORDER BY hours DESC LIMIT 25""", (file_id,)))
        return dict(file=f, days=days, top_apps=top)

    # ---------- device state review
    def _file(self, con, file_id):
        f = con.execute("SELECT * FROM files WHERE file_id = ?", (file_id,)).fetchone()
        if f is None:
            raise ValueError("no such file")
        return dict(f)

    def _paths(self, con, f):
        group = con.execute("SELECT value FROM meta WHERE key = 'group_dir'").fetchone()[0]
        proc = os.path.join(group, f["folder"], "processed")
        return os.path.join(proc, "states", f["stem"] + "_STATES.csv"), os.path.join(proc, f["stem"] + ".csv")

    def _states(self, con, f):
        p = self._paths(con, f)[0]
        return cached(("states", p), lambda: pd.read_csv(p))

    def state_files(self):
        con = self.db()
        hours = {}
        for r in con.execute("SELECT file_id, layer, label, hours FROM state_files"):
            hours.setdefault(r["file_id"], {"strict": {}, "likely": {}})[r["layer"]][r["label"]] = r["hours"]
        rul = {r["stem"]: r["n"] for r in con.execute("SELECT stem, COUNT(*) AS n FROM state_rulings GROUP BY stem")}
        out = []
        for f in rows(con.execute("""SELECT f.file_id, f.folder, f.stem, f.participant, f.role, f.tz, f.first_t, f.last_t,
                r.status, r.note FROM files f LEFT JOIN state_file_review r ON r.stem = f.stem
                ORDER BY f.participant, f.folder""")):
            f["hours"] = hours.get(f["file_id"], {"strict": {}, "likely": {}})
            f["n_rulings"] = rul.get(f["stem"], 0)
            out.append(f)
        return out

    def state_file(self, file_id):
        con = self.db()
        f = self._file(con, file_id)
        days = rows(con.execute("SELECT day, layer, label, hours FROM state_days WHERE file_id = ? ORDER BY day",
                                (file_id,)))
        rules = rows(con.execute("""SELECT layer, rule, label, hours, n FROM state_rules WHERE file_id = ?
            ORDER BY layer, hours DESC""", (file_id,)))
        rev = con.execute("SELECT status, note, reviewer, updated_at FROM state_file_review WHERE stem = ?",
                          (f["stem"],)).fetchone()
        rulings = rows(con.execute("SELECT start, end, label, note, reviewer, updated_at FROM state_rulings "
                                   "WHERE stem = ? ORDER BY start", (f["stem"],)))
        # local days of the file (DST-safe midnights) for the day chart
        d0 = pd.Timestamp(f["first_t"], unit="s", tz="UTC").tz_convert(f["tz"]).tz_localize(None).normalize()
        d1 = pd.Timestamp(f["last_t"], unit="s", tz="UTC").tz_convert(f["tz"]).tz_localize(None).normalize() + pd.DateOffset(days=1)
        mid = pd.date_range(d0, d1, freq="D").tz_localize(f["tz"], ambiguous="NaT", nonexistent="shift_forward")
        e = mid.tz_convert("UTC").as_unit("ns").asi8 / 1e9
        day_edges = [[d, float(a), float(b)] for d, a, b in zip(mid[:-1].strftime("%Y-%m-%d"), e[:-1], e[1:])]
        return dict(file=f, days=days, rules=rules, review=dict(rev) if rev else None, rulings=rulings,
                    day_edges=day_edges)

    def state_strip(self, file_id, layer):
        """The whole file at one layer, consecutive intervals with the same label merged (for the day chart)."""
        if layer not in ("strict", "likely"):
            raise ValueError("layer must be strict or likely")
        con = self.db()
        s = self._states(con, self._file(con, file_id))
        lab = s[layer].to_numpy()
        st = np.where(np.r_[True, lab[1:] != lab[:-1]])[0]
        en = np.r_[st[1:], len(s)] - 1
        code = {l: i for i, l in enumerate(LABEL_ORDER)}
        return dict(labels=LABEL_ORDER, t0=s["start"].to_numpy()[st].round(3).tolist(),
                    t1=s["end"].to_numpy()[en].round(3).tolist(), lab=[code[x] for x in lab[st]])

    def state_window(self, file_id, t0, t1):
        con = self.db()
        f = self._file(con, file_id)
        s = self._states(con, f)
        i0 = int(np.searchsorted(s["end"].to_numpy(), t0, "right"))
        i1 = int(np.searchsorted(s["start"].to_numpy(), t1, "left"))
        iv = s.iloc[i0:min(i1, i0 + MAX_INTERVALS)]
        ev_path = self._paths(con, f)[1]
        ev = cached(("events", ev_path), lambda: load_raw_events(ev_path))
        j0, j1 = np.searchsorted(ev["t"].to_numpy(), [t0, t1])
        evw = ev.iloc[j0:j1]
        rulings = rows(con.execute("SELECT start, end, label, note FROM state_rulings WHERE stem = ? AND end > ? "
                                   "AND start < ? ORDER BY start", (f["stem"], t0, t1)))
        return dict(file=f, window=[t0, t1], intervals=iv.to_dict("records"), intervals_total=i1 - i0,
                    events=evw.iloc[:MAX_EVENTS].rename(columns={"app_package_name": "app", "application_label": "label"})
                    .to_dict("records"), events_total=int(j1 - j0), rulings=rulings)

    # ---------- device state review: blocks
    BLOCK_FROM = """state_blocks b JOIN files f ON f.file_id = b.file_id
        LEFT JOIN state_rulings r ON r.stem = f.stem AND abs(r.start - b.start) < 0.001"""

    def state_summary(self, q):
        con = self.db()
        where, args = "", []
        if q.get("file_id"):
            where, args = "WHERE file_id = ?", [int(q["file_id"])]
        counts = rows(con.execute(f"""SELECT layer, label, SUM(n) AS n, SUM(hours) AS hours FROM state_block_counts
            {where} GROUP BY layer, label""", args))
        listed = rows(con.execute(f"""SELECT b.layer, COUNT(*) AS n, SUM(b.duration_s)/3600.0 AS hours,
            SUM(CASE WHEN r.label IS NOT NULL THEN 1 ELSE 0 END) AS reviewed,
            SUM(CASE WHEN b.reason = 'continuity_check' THEN 1 ELSE 0 END) AS n_check,
            SUM(CASE WHEN b.reason = 'continuity_check' THEN b.duration_s ELSE 0 END)/3600.0 AS h_check,
            SUM(CASE WHEN b.reason = 'conflict' THEN 1 ELSE 0 END) AS n_conflict,
            SUM(CASE WHEN b.reason = 'long_off_check' THEN 1 ELSE 0 END) AS n_long,
            SUM(CASE WHEN b.reason = 'unsure' THEN 1 ELSE 0 END) AS n_unsure
            FROM {self.BLOCK_FROM} WHERE b.reason NOT IN ('app_usage', 'car_review', 'pip_review', 'story_break') {where.replace('WHERE', 'AND').replace('file_id', 'b.file_id')}
            GROUP BY b.layer""", args))
        app_use = rows(con.execute(f"""SELECT b.layer, COUNT(*) AS n, SUM(b.duration_s)/3600.0 AS hours
            FROM {self.BLOCK_FROM} WHERE b.reason = 'app_usage' {where.replace('WHERE', 'AND').replace('file_id', 'b.file_id')}
            GROUP BY b.layer""", args))
        ruled = rows(con.execute(f"""SELECT b.layer, r.label, COUNT(*) AS n, SUM(b.duration_s)/3600.0 AS hours
            FROM {self.BLOCK_FROM} WHERE r.label IS NOT NULL AND b.reason NOT IN ('app_usage', 'car_review', 'pip_review', 'story_break') {where.replace('WHERE', 'AND').replace('file_id', 'b.file_id')}
            GROUP BY b.layer, r.label""", args))
        signs = rows(con.execute(f"""SELECT verdict, how, SUM(n) AS n, SUM(hours) AS hours FROM state_signs {where}
            GROUP BY verdict, how ORDER BY verdict, hours DESC""", args))
        sigs = rows(con.execute(f"""SELECT signature, COUNT(DISTINCT file_id) AS files FROM state_signs {where}
            GROUP BY signature""", args))
        return dict(counts=counts, listed=listed, ruled=ruled, review_min_s=300, signs=signs, signatures=sigs, app_usage=app_use)

    def state_profile(self, file_id, t0, t1):
        """The segment profile of a file inside [t0, t1]: the silence, key-event and app tracks."""
        con = self.db()
        base = self._paths(con, self._file(con, file_id))[0][:-len("_STATES.csv")]
        out = {}
        cp = base + "_PROFILE_CHAIN.csv"
        if os.path.exists(cp):
            ch = cached(("profile", cp), lambda: pd.read_csv(cp, keep_default_na=False))
            c = ch[(ch["end"] >= t0) & (ch["start"] <= t1)]
            if len(c) > 3000:
                c = c[c["duration_s"] >= (t1 - t0) / 1500]
            out["chain"] = c[["start", "end", "n_nodes", "n_apps", "path", "start_logged", "end_logged"]].to_dict("records")
        for name, path in (("profile", base + "_PROFILE.csv"), ("app", base + "_PROFILE_APP.csv")):
            if not os.path.exists(path):
                return dict(missing=True)
            df = cached(("profile", path), lambda path=path: pd.read_csv(path, keep_default_na=False))
            x = df[(df["end"] >= t0) & (df["start"] <= t1)]
            if name == "app" and len(x) > 4000:                 # too many to draw: keep what is visible at this zoom
                x = x[(x["duration_s"] >= (t1 - t0) / 1500) | (x["flag"] == "no start")]
            out[name] = x[["kind", "start", "end", "app", "flag", "n"]].to_dict("records") if name == "profile" \
                else x[["start", "end", "app", "flag"]].to_dict("records")
        return out

    def state_review_files(self, q):
        """Per file: how many quiet stretches are on the review list of a layer, how many are ruled, their hours."""
        where, args = ["b.layer = ?", "b.reason NOT IN ('app_usage', 'car_review', 'pip_review', 'story_break')"], [q.get("layer", "likely")]
        if q.get("role") in ("parent", "child"):
            where.append("f.role = ?")
            args.append(q["role"])
        return rows(self.db().execute(f"""SELECT f.file_id, f.participant, f.role, f.folder, f.first_t, f.last_t,
            COUNT(*) AS n, SUM(CASE WHEN r.label IS NOT NULL THEN 1 ELSE 0 END) AS ruled,
            SUM(b.duration_s)/3600.0 AS hours, fr.status
            FROM {self.BLOCK_FROM} LEFT JOIN state_file_review fr ON fr.stem = f.stem
            WHERE {' AND '.join(where)} GROUP BY f.file_id ORDER BY f.participant, f.folder""", args))

    def state_blocks(self, q):
        where, args = ["b.layer = ?"], [q.get("layer", "likely")]
        if q.get("label") and q["label"] != "all":
            where.append("b.label = ?")
            args.append(q["label"])
        if q.get("file_id"):
            where.append("b.file_id = ?")
            args.append(int(q["file_id"]))
        if q.get("role") in ("parent", "child"):
            where.append("f.role = ?")
            args.append(q["role"])
        if q.get("status") == "todo":
            where.append("r.label IS NULL")
        elif q.get("status") == "done":
            where.append("r.label IS NOT NULL")
        if q.get("reason") in ("unsure", "continuity_check", "conflict", "long_off_check", "no_logging", "app_usage", "car_review", "pip_review", "story_break"):
            where.append("b.reason = ?")
            args.append(q["reason"])
        else:                                   # the app-usage stretches are a list of their own, not review items
            where.append("b.reason NOT IN ('app_usage', 'car_review', 'pip_review', 'story_break')")
        if q.get("min_s"):
            where.append("b.duration_s >= ?")
            args.append(float(q["min_s"]))
        if q.get("inside") == "dark":          # no event between the two that bound the block
            where.append("b.n_events <= 2")
        elif q.get("inside") == "events":
            where.append("b.n_events > 2")
        sql = f"""SELECT b.block_id, b.file_id, b.layer, b.block_no, b.start, b.end, b.duration_s, b.label, b.n_events, b.reason, b.off_sign, b.on_sign, b.boot_score, b.app,
            f.participant, f.role, f.folder, f.tz, r.label AS ruling FROM {self.BLOCK_FROM}
            WHERE {' AND '.join(where)} ORDER BY {'b.start ASC' if q.get('order') == 'time' else 'b.duration_s DESC'} LIMIT ?"""
        con = self.db()
        total = con.execute(f"SELECT COUNT(*) FROM {self.BLOCK_FROM} WHERE {' AND '.join(where)}", args).fetchone()[0]
        return dict(total=total, blocks=rows(con.execute(sql, args + [int(q.get("limit", 1000))])))

    def _events_for(self, con, f):
        ev_path = self._paths(con, f)[1]
        return cached(("events", ev_path), lambda: load_raw_events(ev_path))

    @staticmethod
    def _ev_rows(ev, i0, i1):
        x = ev.iloc[i0:i1].rename(columns={"app_package_name": "app", "application_label": "label"})
        out = x.to_dict("records")
        for k, r in zip(range(i0, i1), out):
            r["i"] = k
        return out

    def state_block(self, block_id, context):
        con = self.db()
        b = con.execute(f"""SELECT b.*, f.stem, f.participant, f.role, f.folder, f.tz, f.raw_name, r.label AS ruling,
            r.note AS ruling_note, r.updated_at AS ruling_at FROM {self.BLOCK_FROM} WHERE b.block_id = ?""",
                        (block_id,)).fetchone()
        if b is None:
            raise ValueError("no such block")
        b = dict(b)
        f = self._file(con, b["file_id"])
        ev = self._events_for(con, f)
        t = ev["t"].to_numpy()
        # events of the block: from the event that starts it to the event that ends it
        j0 = int(np.searchsorted(t, b["start"] - 1e-4, "left"))
        j1 = int(np.searchsorted(t, b["end"] + 1e-4, "right"))
        inside = j1 - j0
        if inside > MAX_EVENTS:      # very long blocks: the first and last events of the block, plus context
            idx = [(max(0, j0 - context), j0 + MAX_EVENTS // 2), (j1 - MAX_EVENTS // 2, min(len(t), j1 + context))]
        else:
            idx = [(max(0, j0 - context), min(len(t), j1 + context))]
        parts = [self._ev_rows(ev, a, c) for a, c in idx]
        # the neighbouring blocks (likely layer) for orientation
        s = self._states(con, f)
        lay = b["layer"]
        st, en = s["start"].to_numpy(), s["end"].to_numpy()
        k0 = int(np.searchsorted(st, b["start"] - 1e-4, "left"))     # first interval of the block
        k1 = int(np.searchsorted(en, b["end"] - 1e-4, "left"))       # last interval of the block
        prev_lab = s[lay].iat[k0 - 1] if k0 > 0 else None
        next_lab = s[lay].iat[k1 + 1] if k1 + 1 < len(s) else None
        return dict(block=b, parts=parts, n_events_total=len(t), block_i=[j0, j1 - 1], inside=inside,
                    before_label=prev_lab, after_label=next_lab)

    def state_events(self, file_id, i0, i1):
        con = self.db()
        ev = self._events_for(con, self._file(con, file_id))
        i0, i1 = max(0, i0), min(len(ev), i1, i0 + MAX_EVENTS)
        return dict(events=self._ev_rows(ev, i0, i1), n_events_total=len(ev))

    def state_rulings_bulk(self, b):
        """One ruling for many blocks (the reviewer's quick action). label "" removes their rulings;
        label "still_unsure" stores each block's own unsure label."""
        ids = [int(x) for x in b.get("block_ids", [])]
        lab = b.get("label") or ""
        if lab and lab != "still_unsure" and lab not in STATE_LABELS:
            return {"error": f"unknown label {lab}"}
        con = self.db()
        now = datetime.datetime.now().isoformat(timespec="seconds")
        n = 0
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            rs = con.execute(f"""SELECT f.stem, b.start, b.end, b.label FROM state_blocks b JOIN files f ON f.file_id = b.file_id
                WHERE b.block_id IN ({','.join('?' * len(chunk))})""", chunk).fetchall()
            for stem, start, end, blabel in rs:
                if not lab:
                    con.execute("DELETE FROM state_rulings WHERE stem = ? AND abs(start - ?) < 0.001", (stem, start))
                else:
                    con.execute("""INSERT INTO state_rulings VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(stem, start) DO UPDATE SET
                        end=excluded.end, label=excluded.label, note=excluded.note, reviewer=excluded.reviewer,
                        updated_at=excluded.updated_at""",
                                (stem, start, end, (blabel if str(blabel).startswith("Unsure") else "Unsure 3") if lab == "still_unsure" else lab, b.get("note") or "",
                                 getpass.getuser(), now))
                n += 1
        con.commit()
        return {"ok": True, "n": n}

    def state_review(self, b):
        con = self.db()
        f = self._file(con, int(b["file_id"]))
        st = b.get("status") or ""
        if st not in ("", "ok", "problem"):
            return {"error": "status must be ok or problem"}
        if not st:
            con.execute("DELETE FROM state_file_review WHERE stem = ?", (f["stem"],))
        else:
            con.execute("""INSERT INTO state_file_review VALUES (?, ?, ?, ?, ?) ON CONFLICT(stem) DO UPDATE SET
                status=excluded.status, note=excluded.note, reviewer=excluded.reviewer, updated_at=excluded.updated_at""",
                        (f["stem"], st, b.get("note") or "", getpass.getuser(),
                         datetime.datetime.now().isoformat(timespec="seconds")))
        con.commit()
        return {"ok": True}

    def state_ruling(self, b):
        con = self.db()
        f = self._file(con, int(b["file_id"]))
        start = float(b["start"])
        lab = b.get("label") or ""
        if not lab:
            con.execute("DELETE FROM state_rulings WHERE stem = ? AND start = ?", (f["stem"], start))
        else:
            if lab not in STATE_LABELS:
                return {"error": f"unknown label {lab}"}
            con.execute("""INSERT INTO state_rulings VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(stem, start) DO UPDATE SET
                end=excluded.end, label=excluded.label, note=excluded.note, reviewer=excluded.reviewer,
                updated_at=excluded.updated_at""",
                        (f["stem"], start, float(b["end"]), lab, b.get("note") or "", getpass.getuser(),
                         datetime.datetime.now().isoformat(timespec="seconds")))
        con.commit()
        return {"ok": True}

    _blk_cache = {}

    def block_nbr(self, q):
        """A device-state block next to another one, with its events (David, 10-17: scroll up / down to the block before
        and after). q: folder, block_id, dir = prev | next. Reads <STATE_DIR>/<folder>/_review/screen_blocks_<file>.csv
        and the file's processed events."""
        from eyeslib.states import device_state as ds
        folder, bid, d = q["folder"], q["block_id"], q.get("dir", "next")
        pid = bid.split("/")[0]; base = os.path.join(STATE_DIR, folder)
        key = (folder, pid)
        if key not in self._blk_cache:
            B = pd.read_csv(os.path.join(base, "_review", f"screen_blocks_{pid}.csv"))
            f = glob.glob(os.path.join(base, "processed", f"{pid}_Chronicle*_sorted_uniq_reordered.csv"))[0]
            ev = ds.load_events(f)
            ev = ev[~ev.name.isin(["Standby Bucket Changed", "Notification Interruption", "Notification Seen"])]
            if len(self._blk_cache) > 6: self._blk_cache.clear()
            self._blk_cache[key] = (B, ev.t.to_numpy(), ev.name.to_numpy(), ev.app_package_name.astype(str).to_numpy())
        B, t, nm, pk = self._blk_cache[key]
        i = B.index[B.block_id == bid]
        if not len(i): return {"error": f"no block {bid}"}
        j = int(i[0]) + (-1 if d == "prev" else 1)
        if j < 0 or j >= len(B): return {"block": None}
        b = B.iloc[j]
        lo, hi = np.searchsorted(t, b.start_t - 1e-3, "left"), np.searchsorted(t, b.end_t + 1e-3, "right")
        rows = [[float(t[k]), nm[k], pk[k], "nbr"] for k in range(lo, hi)]
        if len(rows) > 200: rows = rows[:100] + [[None, f"... {len(rows) - 200} more events ...", "", "nbr"]] + rows[-100:]
        lost = b.lost if isinstance(b.get("lost"), str) else ""
        return {"block": dict(id=b.block_id, block=b.block, t0=float(b.start_t), t1=float(b.end_t), start_by=str(b.start_by),
                              end_by=str(b.end_by), lost=lost, why=b.why if isinstance(b.why, str) else "", cycle=int(b.cycle)),
                "events": rows}

    def state_review_items(self):
        items = []
        for fn in sorted(glob.glob(os.path.join(STATE_DIR, "*", "_review", "state_review.json"))):
            with open(fn) as fh:
                items += [dict(it, list="repeat") for it in json.load(fh)["items"]]
        totals = {}
        for fn in sorted(glob.glob(os.path.join(STATE_DIR, "*", "_review", "block_review.json"))):
            with open(fn) as fh:
                d = json.load(fh)
            items += d["items"]; totals[d["folder"]] = d.get("totals", {})
        for name in ("eventlost_review.json", "long_screenon_review.json"):
            for fn in sorted(glob.glob(os.path.join(STATE_DIR, "*", "_review", name))):
                with open(fn) as fh:
                    items += json.load(fh)["items"]
        con = self.db()
        saved = {r["id"]: dict(r) for r in con.execute("SELECT * FROM state_chain_review")}
        for it in items:
            v = saved.get(it["id"], {})
            it.update(verdict=v.get("verdict", ""), comment=v.get("comment", ""), updated_at=v.get("updated_at", ""))
        return {"dir": STATE_DIR, "items": items, "block_totals": totals}

    def state_review_save(self, b):
        verdict = b.get("verdict") or ""
        if verdict and verdict not in STATE_VERDICTS:
            return {"error": f"unknown verdict {verdict}"}
        con = self.db()
        if not verdict and not (b.get("comment") or "").strip():
            con.execute("DELETE FROM state_chain_review WHERE id = ?", (b["id"],)); con.commit()
            return {"ok": True, "updated_at": ""}
        now = datetime.datetime.now().isoformat(timespec="seconds")
        con.execute("""INSERT INTO state_chain_review VALUES (?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET verdict=excluded.verdict,
            comment=excluded.comment, reviewer=excluded.reviewer, updated_at=excluded.updated_at""",
                    (b["id"], verdict, b.get("comment") or "", getpass.getuser(), now))
        con.commit()
        return {"ok": True, "updated_at": now}

    def scenarios(self):
        d = load_scenarios()
        con = self.db()
        notes = {r["sid"]: dict(r) for r in con.execute("SELECT * FROM scenario_comments")}
        for it in d["scenarios"]:
            n = notes.get(it["id"], {})
            it.update(comment=n.get("comment", ""), reviewer=n.get("reviewer", ""), updated_at=n.get("updated_at", ""))
        return d

    def scenario_comment(self, b):
        sid = str(b["id"])
        text = b.get("comment") or ""
        con = self.db()
        if not text.strip():
            con.execute("DELETE FROM scenario_comments WHERE sid = ?", (sid,))
            con.commit()
            return {"ok": True, "updated_at": ""}
        now = datetime.datetime.now().isoformat(timespec="seconds")
        con.execute("""INSERT INTO scenario_comments VALUES (?, ?, ?, ?) ON CONFLICT(sid) DO UPDATE SET
            comment=excluded.comment, reviewer=excluded.reviewer, updated_at=excluded.updated_at""",
                    (sid, text, getpass.getuser(), now))
        con.commit()
        return {"ok": True, "updated_at": now}

    def export(self, q):
        """All sessions with verdicts applied (streamed CSV)."""
        con = self.db()
        where, args = "", []
        if q.get("file_id"):
            where, args = "WHERE s.file_id = ?", [int(q["file_id"])]
        cur = con.execute(f"SELECT {SESSION_COLS} FROM {SESSION_FROM} {where} ORDER BY f.participant, s.start", args)
        cols = ["participant", "role", "folder", "session_id", "start_utc", "end_utc", "duration_s", "n_apps",
                "first_app", "last_app", "end_evidence", "quiet_s", "hb_in_quiet", "n_usage", "n_heartbeats",
                "reasons", "verdict", "reviewed_end_utc", "reviewed_duration_s", "latest_end_utc",
                "max_duration_s", "included", "note"]
        self.send_response(200)
        self.send_header("Content-Type", "text/csv")
        self.send_header("Content-Disposition", "attachment; filename=sessions_reviewed.csv")
        self.end_headers()

        def iso(x):
            return datetime.datetime.fromtimestamp(x, datetime.timezone.utc).isoformat(timespec="milliseconds")
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(cols)
        for r in cur:
            end = r["end"]
            if r["verdict"] in CUT_VERDICTS and r["truncate_at"]:
                end = r["truncate_at"]
            latest = r["latest_end"] if r["verdict"] == "log_missing" and r["latest_end"] else end
            inc = 0 if r["verdict"] == "exclude" else 1
            w.writerow([r["participant"], r["role"], r["folder"], r["session_id"], iso(r["start"]), iso(r["end"]),
                        round(r["duration_s"], 3), r["n_apps"], r["first_app"], r["last_app"], r["end_evidence"],
                        round(r["quiet_s"], 3), r["hb_in_quiet"], r["n_usage"], r["n_heartbeats"], r["reasons"], r["verdict"] or "", iso(end), round(end - r["start"], 3) if inc else 0,
                        iso(latest), round(latest - r["start"], 3) if inc else 0, inc, r["note"] or ""])
            if buf.tell() > 1 << 20:
                self.wfile.write(buf.getvalue().encode())
                buf.seek(0)
                buf.truncate()
        self.wfile.write(buf.getvalue().encode())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.expanduser("~/workspace/screen_time/by_group/A1/_review/eyes_review.sqlite"))
    ap.add_argument("--port", type=int, default=8877)
    a = ap.parse_args()
    if not os.path.exists(a.db):
        raise SystemExit(f"no database at {a.db}; run python -m eyes_review.ingest first")
    Handler.db_path = a.db
    con = sqlite3.connect(a.db)          # databases made before the log_missing verdict
    if "latest_end" not in [c[1] for c in con.execute("PRAGMA table_info(verdicts)")]:
        con.execute("ALTER TABLE verdicts ADD COLUMN latest_end REAL")
        con.commit()
    con.executescript("""
        CREATE TABLE IF NOT EXISTS state_files (file_id INTEGER, layer TEXT, label TEXT, hours REAL);
        CREATE TABLE IF NOT EXISTS state_days (file_id INTEGER, day TEXT, layer TEXT, label TEXT, hours REAL);
        CREATE TABLE IF NOT EXISTS state_rules (file_id INTEGER, layer TEXT, rule TEXT, label TEXT, hours REAL, n INTEGER);
        CREATE TABLE IF NOT EXISTS state_block_counts (file_id INTEGER, layer TEXT, label TEXT, n INTEGER, hours REAL);
        CREATE TABLE IF NOT EXISTS state_blocks (block_id INTEGER PRIMARY KEY, file_id INTEGER, layer TEXT, block_no INTEGER,
            start REAL, end REAL, duration_s REAL, label TEXT, rules TEXT, n_events INTEGER,
            left_event TEXT, left_app TEXT, right_event TEXT, right_app TEXT, reason TEXT,
            off_sign TEXT, on_sign TEXT, boot_score REAL, app TEXT);
        CREATE TABLE IF NOT EXISTS state_signs (file_id INTEGER, verdict TEXT, how TEXT, n INTEGER, hours REAL, signature TEXT);
        CREATE TABLE IF NOT EXISTS state_file_review (stem TEXT PRIMARY KEY, status TEXT, note TEXT, reviewer TEXT, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS state_rulings (stem TEXT, start REAL, end REAL, label TEXT, note TEXT, reviewer TEXT,
            updated_at TEXT, PRIMARY KEY (stem, start));
        CREATE TABLE IF NOT EXISTS scenario_comments (sid TEXT PRIMARY KEY, comment TEXT, reviewer TEXT, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS state_chain_review (id TEXT PRIMARY KEY, verdict TEXT, comment TEXT, reviewer TEXT, updated_at TEXT);""")
    con.close()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print(f"EYES review on http://127.0.0.1:{a.port}  (db {a.db})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
