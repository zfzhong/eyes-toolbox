"""
Write the segment profile of every log of a folder: python -m eyeslib.runners.run_profiles <folder> [--workers N]
  <folder>/processed/states/<stem>_PROFILE.csv       silence and key-event tracks
  <folder>/processed/states/<stem>_PROFILE_APP.csv   app track (user apps in front)
  <folder>/processed/states/<stem>_PROFILE_CHAIN.csv app chains
Run after run_boot_signatures (the Off segments use the boot signature).
"""
import argparse, glob, json, os, time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from eyeslib.states import device_state as ds, profile
from eyeslib.runners.run_device_states import signature_for


def one(args):
    infile, out_dir, pooled = args
    ev = ds.load_events(infile)
    prof, app = profile.build(ev, sig=signature_for(infile, out_dir, pooled))
    stem = Path(infile).stem
    prof.round(3).to_csv(os.path.join(out_dir, stem + "_PROFILE.csv"), index=False)
    app.round(3).to_csv(os.path.join(out_dir, stem + "_PROFILE_APP.csv"), index=False)
    profile.chain_track(app[app["kind"] == "in_front"] if len(app) else app).round(3).to_csv(
        os.path.join(out_dir, stem + "_PROFILE_CHAIN.csv"), index=False)
    return stem, len(prof), len(app)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--pooled", default=None)
    a = ap.parse_args(argv)
    proc = os.path.join(a.dir, "processed")
    out = os.path.join(proc, "states")
    os.makedirs(out, exist_ok=True)
    pp = Path(a.pooled) if a.pooled else Path(a.dir).resolve().parent / "_states" / "boot_signature_pooled.json"
    pooled = None
    if pp.exists():
        with open(pp) as f:
            pooled = json.load(f)["core"]
    files = sorted(glob.glob(os.path.join(proc, "*_sorted_uniq_reordered.csv")))
    t0 = time.time()
    with ProcessPoolExecutor(a.workers) as ex:
        for i, (stem, n1, n2) in enumerate(ex.map(one, [(f, out, pooled) for f in files]), 1):
            print(f"[{i}/{len(files)}] {stem[:40]} {n1} segments, {n2} app segments", flush=True)
    print(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
