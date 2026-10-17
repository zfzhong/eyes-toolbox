import glob, collections, pandas as pd, os
import sys; REUSE = sys.argv[1] == "reuse"
A = {"Activity Resumed", "Activity Paused", "Activity Stopped"}
depth = collections.Counter(); ex = {}; fifo_ok = fifo_bad = 0
for f in sorted(glob.glob(os.path.expanduser("~/serveraws/media/eyes/days/*/*.csv.gz"))):
    try: d = pd.read_csv(f, usecols=["app_package_name", "app_class_name", "interaction_type", "event_timestamp"], low_memory=False)
    except Exception: continue
    d = d[d.interaction_type.isin(A) | d.interaction_type.isin(["Screen Non-interactive", "Device Shutdown", "Device Startup"])].sort_values("event_timestamp", kind="stable")
    q = collections.defaultdict(list)          # per package: open triplets [class, state]
    for p, c, e, t in zip(d.app_package_name.astype(str), d.app_class_name.astype(str), d.interaction_type, d.event_timestamp):
        if e in ("Device Shutdown", "Device Startup"): q.clear(); continue
        if e == "Screen Non-interactive": continue
        Q = q[p]
        if e == "Activity Resumed":
            back = [x for x in Q if x[0] == c and x[1] == "P"]
            if back and REUSE: back[-1][1] = "R"
            else: Q.append([c, "R"])
        elif e == "Activity Paused":
            for x in Q:
                if x[0] == c and x[1] == "R": x[1] = "P"; break
        else:
            ps = [x for x in Q if x[1] == "P"]
            mine = [x for x in ps if x[0] == c]
            if ps and mine:
                if ps[0] is mine[0]: fifo_ok += 1
                else: fifo_bad += 1
            if mine: Q.remove(mine[0])
        n = len(Q); depth[n] += 1
        if n in (4, 5, 8) and n not in ex: ex[n] = (f.split("/")[-2][:8], os.path.basename(f)[:10], p, [x[0].split(".")[-1] + ":" + x[1] for x in Q])
print("open triplets per app after each event (count of events):", sorted(depth.items())[:12])
print("Stopped matches the oldest Paused (FIFO):", fifo_ok, "| not the oldest:", fifo_bad)
for n in sorted(ex): print(n, ex[n][:3])
T = sum(depth.values()); mx = max(depth)
print("TOTAL", T, "MAX", mx, "SHARES", {k: round(100 * v / T, 2) for k, v in sorted(depth.items()) if k <= 6}, ">=4:", round(100 * sum(v for k, v in depth.items() if k >= 4) / T, 2))
