"""
Re-run the EYES pipeline from `nest` onward (plus pickups), per participant,
after the 2026-09-29 fixes to nest / merge / pickups.

Usage (from the eyes-toolbox repo root):
    python tools/rerun_after_fix.py <cohort_dir> [...] --state state.jsonl [--budget 150]

- Uses exactly the same module entry points and arguments as the Makefile
  runners (nest, merge, fau, allevents, eventstz, visual, pickups, pickupstz),
  and the same key/pairing rules (first file per participant key, glob order).
- Before overwriting anything, copies the existing output into
  <cohort>/processed/_before_fix_2026-09-29/ (only once per file).
- Resumable: finished steps are recorded in --state; re-run with the same
  arguments to continue. --budget stops starting new steps after N seconds.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

BACKUP = "_before_fix_2026-09-29"
PY = sys.executable


def key_of(name):
    t = name.split("_")
    return "%s_%s" % (t[0], t[1])


def first_by_key(files):
    m = {}
    for f in files:
        m.setdefault(key_of(f.name), f)
    return m


def backup(proc, path):
    """copy path into the backup folder (preserving segments/visual subdir) once."""
    if not path.exists():
        return
    rel = path.relative_to(proc)
    dst = proc / BACKUP / rel
    if dst.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".part")  # atomic: never leave a truncated backup
    shutil.copy2(path, tmp)
    os.replace(tmp, dst)


def run(cmd, stdout=None):
    r = subprocess.run(cmd, stdout=stdout or subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(map(str, cmd))}\n{r.stderr[-2000:]}")


def plan(cohort):
    """list of (unit_id, [(step_name, outputs_to_backup, fn)])"""
    d = Path(cohort)
    proc = d / "processed"
    seg = proc / "segments"
    raw = first_by_key(list(d.glob("*.csv")))
    blocks_by_key = first_by_key([f for f in seg.glob("*.csv") if re.search(r"_BLOCKS.csv$", f.name)])
    uniq_by_key = first_by_key(list(proc.glob("*_uniq.csv")))

    units = []
    for app1 in proc.glob("*.csv"):
        if not re.search(r"_app_1.csv$", app1.name):
            continue
        key = key_of(app1.name)
        nested = proc / app1.name.replace("_app_1.csv", "_primary_secondary_nested.csv")
        psfau = proc / nested.name.replace("_nested.csv", "_fau.csv")
        fau_usage = proc / psfau.name.replace("_primary_secondary_fau.csv", "_fau_usage.csv")
        events = proc / f"{key}_events.csv"
        events_tz = proc / f"{key}_events_tz.csv"
        png = proc / "visual" / f"{fau_usage.stem}.png"
        steps = [
            ("nest", [nested],
             lambda a=app1, n=nested: run([PY, "-m", "eyeslib.usage.separate_overlap_screen_time", str(a), "2", str(n)])),
        ]
        if key in blocks_by_key:
            steps.append(("merge", [psfau],
                          lambda n=nested, b=blocks_by_key[key]: run([PY, "-m", "eyeslib.usage.merge_app_status", str(n), str(b), "5"])))
            steps.append(("fau", [fau_usage],
                          lambda p=psfau, o=fau_usage: run([PY, "-m", "eyeslib.exports.gen_fau_screen_time", str(p),
                                                            "--statuses", "ACTIVE", "--mode", "primary", "--output", str(o)])))
            if key in uniq_by_key:
                steps.append(("allevents", [events],
                              lambda u=uniq_by_key[key], p=psfau, o=events: run([PY, "-m", "eyeslib.exports.gen_all_events", str(u), str(p), str(o)])))
                if key in raw:
                    steps.append(("eventstz", [events_tz],
                                  lambda r=raw[key], e=events, o=events_tz: run([PY, "-m", "eyeslib.exports.gen_timezone_columns_for_events", str(r), str(e), str(o)])))
            steps.append(("visual", [png],
                          lambda f=fau_usage, o=proc / "visual": run([PY, "-c",
                              "import sys; from pathlib import Path; from eyeslib.usage.visualize_app_usage import visualize_app_usage as v; "
                              "p=Path(sys.argv[1]); o=Path(sys.argv[2]); o.mkdir(exist_ok=True); v(p, o)", str(f), str(o)])))
        units.append((f"app:{key}", steps))

    pickups_all = []
    for b in seg.glob("*.csv"):
        if not re.search(r"_BLOCKS.csv$", b.name):
            continue
        p = seg / b.name.replace("_BLOCKS.csv", "_PICKUPS.csv")
        pickups_all.append(p)
        units.append((f"pickups:{b.name}", [
            ("pickups", [p], lambda b=b, p=p: run([PY, "-m", "eyeslib.exports.gen_pickups", str(b), "5", "5", str(p)])),
        ]))
    pick_by_key = first_by_key(pickups_all)
    for key, p in pick_by_key.items():
        if key in raw:
            tz = seg / p.name.replace("_PICKUPS.csv", "_PICKUPS_tz.csv")
            units.append((f"pickupstz:{key}", [
                ("pickupstz", [tz], lambda r=raw[key], p=p, tz=tz: run([PY, "-m", "eyeslib.exports.gen_timezone_columns_for_pickups", str(r), str(p), str(tz)])),
            ]))
    # pickupstz must come after all pickups in this cohort
    units.sort(key=lambda u: u[0].startswith("pickupstz:"))
    return proc, units


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--state", required=True)
    ap.add_argument("--budget", type=float, default=0)
    a = ap.parse_args()

    done = set()
    if os.path.exists(a.state):
        with open(a.state) as f:
            for line in f:
                r = json.loads(line)
                if r["status"] == "ok":
                    done.add((r["cohort"], r["unit"], r["step"]))

    start = time.time()
    n_run = 0
    with open(a.state, "a") as log:
        for d in a.dirs:
            proc, units = plan(d)
            for unit, steps in units:
                for name, outs, fn in steps:
                    if (d, unit, name) in done:
                        continue
                    if a.budget and time.time() - start > a.budget:
                        print(f"BUDGET_EXHAUSTED after {n_run} steps")
                        return
                    t0 = time.time()
                    status = "ok"
                    try:
                        for o in outs:
                            backup(proc, o)
                        fn()
                    except Exception as e:
                        status = "error: " + str(e)[-1500:]
                    log.write(json.dumps({"cohort": d, "unit": unit, "step": name, "status": status,
                                          "secs": round(time.time() - t0, 1)}) + "\n")
                    log.flush()
                    n_run += 1
                    if status != "ok":
                        print(f"ERROR {d} {unit} {name}: {status[:300]}")
    print(f"ALL_DONE ({n_run} steps this call)")


if __name__ == "__main__":
    main()
