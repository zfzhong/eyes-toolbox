"""Learn the boot signature of every device in a processing group (eyeslib.states.device_state).

For each reordered log in <group_dir>/<folder>/processed:
    processed/states/<stem>_BOOTSIG.json   {"core": [items], "n_boots": N}
and for the group:
    <group_dir>/_states/boot_signature_pooled.json   the pooled signature, for devices with too few
                                                     confirmed boots (one signature per participant device:
                                                     the export with the most confirmed boots)

Run this before run_device_states.

Usage: python -m eyeslib.runners.run_boot_signatures <group_dir> [--workers 4]
"""
import argparse
import json
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from eyeslib.states.device_state import SIG_MIN_BOOTS, SIG_MIN_ITEMS, boot_core, load_events, pooled_core


def one(infile):
    core, n = boot_core(load_events(infile))
    out_dir = Path(infile).parent / "states"
    out_dir.mkdir(exist_ok=True)
    with open(out_dir / (Path(infile).name[:-4] + "_BOOTSIG.json"), "w") as f:
        json.dump({"core": core, "n_boots": n}, f)
    return str(infile), core, n


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("group_dir")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    group = Path(os.path.expanduser(a.group_dir))
    files = sorted(str(f) for d in group.iterdir() if d.is_dir() and not d.name.startswith("_")
                   for f in (d / "processed").glob("*_reordered.csv"))
    with ProcessPoolExecutor(a.workers) as ex:
        res = list(ex.map(one, files))
    # one signature per device: the participant id is the start of the file name (e.g. 4075_P01)
    best = {}
    for f, core, n in res:
        dev = "_".join(Path(f).name.split("_")[:2])
        if n >= SIG_MIN_BOOTS and len(core) >= SIG_MIN_ITEMS and n > best.get(dev, (0, None))[0]:
            best[dev] = (n, core)
    pooled = pooled_core([c for _, c in best.values()])
    (group / "_states").mkdir(exist_ok=True)
    with open(group / "_states" / "boot_signature_pooled.json", "w") as f:
        json.dump({"core": pooled, "n_devices": len(best)}, f)
    own = sum(1 for _, c, n in res if n >= SIG_MIN_BOOTS and len(c) >= SIG_MIN_ITEMS)
    print(f"{len(res)} logs; own signature: {own}; devices pooled: {len(best)}; pooled signature: {len(pooled)} items")
