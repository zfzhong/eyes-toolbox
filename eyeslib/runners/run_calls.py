"""Phone calls into the screen-time output (eyeslib.states.calls; David 10-13: "phone call should be treated
separately"; 10-14: "separate the phone call from A1, like what we did for car projection").

For each participant in <dir>/processed (the same pairing as the other runners: the first reordered log per
participant key, in glob order):
  - <key>_fau_usage.csv: the part of a call app's ACTIVE row inside a call (plus the "Call ended" screen)
    becomes a row with device_status CALL (not screen time). Other apps used during a call stay ACTIVE.
    Rewritten in place; `make fau` writes it afresh each run.
  - <key>_calls.csv: the calls (start, end, package, seconds, outcome, device_started, front_s = time the
    call screen was in front).
Usage: python -m eyeslib.runners.run_calls <dir>
"""
import sys
from pathlib import Path

import pandas as pd

from eyeslib.states import calls as callsmod

COLS = ["start", "end", "package", "seconds", "outcome", "device_started", "front_s"]


def key_of(name):
    t = name.split("_")
    return "%s_%s" % (t[0], t[1])


def one(log_path, fau_path, out_path):
    log = pd.read_csv(log_path, usecols=["app_package_name", "interaction_type", "event_timestamp"], dtype=str)
    cl = callsmod.calls(log)
    fau = pd.read_csv(fau_path)
    if not cl or fau.empty:
        pd.DataFrame(columns=COLS).to_csv(out_path, index=False)
        return 0, 0.0
    a = pd.to_datetime(fau["resume_time"], format="mixed", utc=True)
    b = pd.to_datetime(fau["end_time"], format="mixed", utc=True)
    is_call_app = fau["app_package_name"].isin(callsmod.CALL_PKGS) & (fau["device_status"] == "ACTIVE")
    rows, moved, front = [], 0.0, [0.0] * len(cl)
    for i, r in enumerate(fau.itertuples(index=False)):
        if not is_call_app.iloc[i]:
            rows.append(r._asdict()); continue
        screen, call = callsmod.call_time([(r.app_package_name, a.iloc[i], b.iloc[i])], cl)
        first = True
        for kind, parts in (("ACTIVE", screen), ("CALL", call)):
            for _, x, y in parts:
                d = r._asdict()
                d.update(resume_time=str(x), end_time=str(y), duration=round((y - x).total_seconds(), 3),
                         device_status=kind, secondary_duration=r.secondary_duration if first and kind == "ACTIVE" else 0.0)
                rows.append(d)
                first = False
                if kind == "CALL":
                    moved += d["duration"]
                    for j, c in enumerate(cl):
                        if c["pkg"] == r.app_package_name:
                            front[j] += max(0.0, (min(y, c["end"] + pd.Timedelta(seconds=5)) - max(x, c["start"])).total_seconds())
    pd.DataFrame(rows, columns=fau.columns).to_csv(fau_path, index=False)
    pd.DataFrame([{"start": c["start"], "end": c["end"], "package": c["pkg"], "seconds": round(c["seconds"], 1),
                   "outcome": c["outcome"], "device_started": c["device_started"], "front_s": round(front[j], 1)}
                  for j, c in enumerate(cl)], columns=COLS).to_csv(out_path, index=False)
    return len(cl), moved


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:", sys.argv[0], "<dir>"); sys.exit(1)
    proc = Path(sys.argv[1]) / "processed"
    logs = {}
    for f in proc.glob("*_sorted_uniq_reordered.csv"):
        logs.setdefault(key_of(f.name), f)
    for fau in sorted(proc.glob("*_fau_usage.csv")):
        key = key_of(fau.name)
        if key not in logs:
            print(f"[calls] {key}: no log"); continue
        n, moved = one(logs[key], fau, proc / f"{key}_calls.csv")
        print(f"[calls] {key}: {n} calls, {moved / 3600:.2f} h of call screen moved out of screen time")
