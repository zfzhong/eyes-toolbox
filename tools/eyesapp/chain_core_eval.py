import glob, collections, pandas as pd, os, sys
sys.path.insert(0, "/tmp"); import chain_core as cc
A = {"Activity Resumed", "Activity Paused", "Activity Stopped"}; CUT = {"Device Shutdown", "Device Startup"} if len(sys.argv) > 1 else {"Screen Interactive", "Device Shutdown", "Device Startup"}
fails = collections.Counter(); napp = 0; ex = collections.defaultdict(list)
for f in sorted(glob.glob(os.path.expanduser("~/serveraws/media/eyes/days/*/*.csv.gz"))):
    try: d = pd.read_csv(f, usecols=["app_package_name", "app_class_name", "interaction_type", "event_timestamp"], low_memory=False)
    except Exception: continue
    d = d[d.interaction_type.isin(A | CUT)].sort_values("event_timestamp", kind="stable").reset_index(drop=True)
    nm = d.interaction_type.tolist(); pk = d.app_package_name.astype(str).tolist(); cls = d.app_class_name.astype(str).tolist()
    seg = []
    def flush(seg):
        global napp
        if not seg: return
        napp += len(seg); _, F = cc.walk(seg, nm, pk, ("Activity Paused", "Activity Stopped"))
        for k, w, a in F:
            fails[w] += 1
            if len(ex[w]) < 3: ex[w].append((f.split("/")[-2][:8], os.path.basename(f)[:10], [(nm[j][9:], pk[j].split(".")[-1], cls[j].split(".")[-1]) for j in seg[max(seg.index(k) - 4, 0):seg.index(k) + 2]]))
    for i in range(len(nm)):
        if nm[i] in CUT: flush(seg); seg = []
        else: seg.append(i)
    flush(seg)
print(f"EyesApp, class names dropped: {napp:,} activity events; failures:", dict(fails), f"= {1000 * sum(fails.values()) / napp:.2f} per 1,000 events")
for w, L in ex.items():
    print("\n", w)
    for dv, day, s in L: print("   ", dv, day, s)
