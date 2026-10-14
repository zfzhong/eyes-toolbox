"""Device states for every reordered log in <dir>/processed (eyeslib.states.device_state).

Writes, in <dir>/processed/states/:
    <stem>_STATES.csv   the merged interval table (strict and likely labels, the rule behind each)
    <stem>_QUIET.csv    the quiet stretches a person should look at, with the Off-or-On evidence
    <stem>_SIGNS.csv    every quiet stretch of at least the tolerance: verdict and the sign that decided it

Uses the boot signatures written by run_boot_signatures (run that first): the device's own
(<stem>_BOOTSIG.json) when it has enough confirmed boots and items, otherwise the pooled one
(<dir>/../_states/boot_signature_pooled.json, or --pooled).

Usage: python -m eyeslib.runners.run_device_states <dir> [--workers 4] [--pooled PATH]
"""
import argparse
import json
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from eyeslib.states.device_state import (SIG_MIN_BOOTS, SIG_MIN_ITEMS, SIG_POOL_SCORE, SIG_SCORE, compute,
                                         interval_labels, load_events, quiet_stretches, stretch_signs)


def signature_for(infile, out_dir, pooled):
    p = os.path.join(out_dir, Path(infile).name[:-4] + "_BOOTSIG.json")
    if os.path.exists(p):
        with open(p) as f:
            own = json.load(f)
        if own["n_boots"] >= SIG_MIN_BOOTS and len(own["core"]) >= SIG_MIN_ITEMS:
            return dict(core=own["core"], cut=SIG_SCORE, kind="device")
    if pooled:
        return dict(core=pooled, cut=SIG_POOL_SCORE, kind="pooled")
    return None


def one(infile, out_dir, pooled):
    ev = load_events(infile)
    sig = signature_for(infile, out_dir, pooled)
    x = interval_labels(ev, sig)
    stem = Path(infile).name[:-4]
    s = compute(ev, x)
    s.to_csv(os.path.join(out_dir, stem + "_STATES.csv"), index=False)
    if x is not None:
        quiet_stretches(ev, x).to_csv(os.path.join(out_dir, stem + "_QUIET.csv"), index=False)
        stretch_signs(ev, x).assign(signature=sig["kind"] if sig else "none").to_csv(
            os.path.join(out_dir, stem + "_SIGNS.csv"), index=False)
    return len(s)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--pooled")
    a = ap.parse_args()
    directory = Path(a.dir) / "processed"
    out_dir = directory / "states"
    out_dir.mkdir(exist_ok=True)
    pp = Path(a.pooled) if a.pooled else Path(a.dir).resolve().parent / "_states" / "boot_signature_pooled.json"
    pooled = json.load(open(pp))["core"] if pp.exists() else None
    if pooled is None:
        print(f"no pooled signature at {pp}: devices without their own signature get none", flush=True)
    files = sorted(directory.glob("*_reordered.csv"))
    with ProcessPoolExecutor(a.workers) as ex:
        futs = {ex.submit(one, str(f), str(out_dir), pooled): f for f in files}
        for i, fut in enumerate(as_completed(futs), 1):
            f = futs[fut]
            try:
                print(f"[{i}/{len(files)}] {f.name[:40]} {fut.result()} rows", flush=True)
            except Exception as e:  # keep going
                print(f"[{i}/{len(files)}] ERROR {f.name}: {e!r}", flush=True)
