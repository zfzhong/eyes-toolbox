"""Android Auto periods into the screen-time output (eyeslib.states.car; David 10-13: "the android auto is a
separate category ... we just put them into the android auto period").

For each participant in <dir>/processed (the same pairing as the other runners: the first reordered log per
participant key, in glob order):
  - <key>_fau_usage.csv: every ACTIVE row is split; its parts inside an Android Auto period that are not the
    phone's own unlocked use become rows with device_status ANDROID_AUTO (not screen time). Rewritten in place;
    `make fau` writes it afresh each run.
  - <key>_android_auto.csv: the periods (start, end, minutes, phone_use_s = ACTIVE time kept inside them) and
    the screen left on at each end.
Usage: python -m eyeslib.runners.run_car_periods <dir>
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from eyeslib.states import car


def key_of(name):
    t = name.split("_")
    return "%s_%s" % (t[0], t[1])


def one(log_path, fau_path, out_path):
    log = pd.read_csv(log_path, usecols=lambda c: c in ("app_package_name", "app_class_name", "interaction_type",
                                                        "event_timestamp"), dtype=str)
    tr = car.tracks(log)
    fau = pd.read_csv(fau_path)
    if not tr["proj"] or fau.empty:
        pd.DataFrame(columns=["start", "end", "minutes", "phone_use_s", "after_s"]).to_csv(out_path, index=False)
        return 0, 0.0
    a = pd.to_datetime(fau["resume_time"], format="mixed", utc=True)
    b = pd.to_datetime(fau["end_time"], format="mixed", utc=True)
    ps = np.array([x.value for x, _ in tr["proj"]])
    pe = np.array([y.value for _, y in tr["proj"]])
    # rows that may overlap a period: the last period starting before the row's end ends after its start
    k = np.searchsorted(ps, b.astype("int64").to_numpy(), "left") - 1
    near = (k >= 0) & (pe[np.maximum(k, 0)] > a.astype("int64").to_numpy()) & (fau["device_status"] == "ACTIVE").to_numpy()
    rows, moved = [], 0.0
    phone_in = np.zeros(len(ps))
    for i, r in enumerate(fau.itertuples(index=False)):
        if not near[i]:
            rows.append(r._asdict()); continue
        ph, cr = car.split(str(r.app_package_name), a.iloc[i], b.iloc[i], tr)
        first = True
        for kind, parts in (("ACTIVE", ph), ("ANDROID_AUTO", cr)):
            for x, y in parts:
                d = r._asdict()
                d.update(resume_time=str(x), end_time=str(y), duration=round((y - x).total_seconds(), 3),
                         device_status=kind, secondary_duration=r.secondary_duration if first and kind == "ACTIVE" else 0.0)
                rows.append(d)
                first = False
                if kind == "ANDROID_AUTO":
                    moved += d["duration"]
                else:
                    for j, (p0, p1) in enumerate(tr["proj"]):
                        phone_in[j] += max(0.0, (min(y, p1) - max(x, p0)).total_seconds())
    pd.DataFrame(rows, columns=fau.columns).to_csv(fau_path, index=False)
    after = {}
    for s0, s1 in tr["after"]:
        j = int(np.argmin([abs((s0 - e).total_seconds()) for _, e in tr["proj"]]))
        after[j] = (s1 - s0).total_seconds()
    pd.DataFrame([{"start": p0, "end": p1, "minutes": round((p1 - p0).total_seconds() / 60, 2),
                   "phone_use_s": round(phone_in[j], 1), "after_s": round(after.get(j, 0.0), 1)}
                  for j, (p0, p1) in enumerate(tr["proj"])]).to_csv(out_path, index=False)
    return len(tr["proj"]), moved


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
            print(f"[car] {key}: no log"); continue
        n, moved = one(logs[key], fau, proc / f"{key}_android_auto.csv")
        print(f"[car] {key}: {n} Android Auto periods, {moved / 3600:.2f} h moved out of screen time")
