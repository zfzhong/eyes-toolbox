"""Power-cycle track (eyeslib.states.power) for every reordered log in <dir>/processed.
Writes <dir>/processed/states/<stem>_POWER.csv. Run after run_boot_signatures.
Usage: python -m eyeslib.runners.run_power <dir> [--workers 4] [--pooled PATH]"""
import argparse, json, os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from eyeslib.states.device_state import interval_labels, load_events
from eyeslib.states.power import power_cycles
from eyeslib.runners.run_device_states import signature_for


def one(infile, out_dir, pooled):
    ev = load_events(infile)
    x = interval_labels(ev, signature_for(infile, out_dir, pooled))
    P = power_cycles(ev, x)
    P.to_csv(os.path.join(out_dir, Path(infile).name[:-4] + "_POWER.csv"), index=False)
    return len(P)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("dir"); ap.add_argument("--workers", type=int, default=4); ap.add_argument("--pooled")
    a = ap.parse_args()
    d = Path(a.dir) / "processed"; out = d / "states"; out.mkdir(exist_ok=True)
    pp = Path(a.pooled) if a.pooled else Path(a.dir).resolve().parent / "_states" / "boot_signature_pooled.json"
    pooled = json.load(open(pp))["core"] if pp.exists() else None
    files = sorted(d.glob("*_reordered.csv"))
    with ProcessPoolExecutor(a.workers) as ex:
        futs = {ex.submit(one, str(f), str(out), pooled): f for f in files}
        for i, fut in enumerate(as_completed(futs), 1):
            try: print(f"[{i}/{len(files)}] {futs[fut].name[:40]} {fut.result()} cycles", flush=True)
            except Exception as e: print(f"[{i}/{len(files)}] ERROR {futs[fut].name}: {e!r}", flush=True)
