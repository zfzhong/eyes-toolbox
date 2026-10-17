import glob, collections, pandas as pd, os
A = {"Activity Resumed", "Activity Paused", "Activity Stopped"}
pat = collections.Counter(); apps = collections.Counter(); pairs = collections.Counter(); devs = set(); n_stop = 0; multi = collections.Counter()
for f in sorted(glob.glob(os.path.expanduser("~/serveraws/media/eyes/days/*/*.csv.gz"))):
    try: d = pd.read_csv(f, usecols=["app_package_name", "app_class_name", "interaction_type", "event_timestamp"], low_memory=False)
    except Exception: continue
    d = d[d.interaction_type.isin(A)].sort_values("event_timestamp", kind="stable")
    if not len(d): continue
    front = {}; paused = collections.defaultdict(collections.Counter)
    for p, c, e in zip(d.app_package_name.astype(str), d.app_class_name.astype(str), d.interaction_type):
        if e == "Activity Resumed": front[p] = c
        elif e == "Activity Paused":
            paused[p][c] += 1
            if front.get(p) == c: front.pop(p, None)
        else:
            n_stop += 1
            if p in front and front[p] != c and paused[p][c] > 0:
                pat["Stopped of an earlier screen while another screen of the same app is in front"] += 1; apps[p] += 1
                pairs[(p.split(".")[-1], c.split(".")[-1], front[p].split(".")[-1])] += 1; devs.add(f.split("/")[-2][:8])
            if paused[p][c] > 0: paused[p][c] -= 1
print(f"{n_stop:,} Stopped in all EyesApp days;", dict(pat), "on", len(devs), "devices")
print("apps:"); [print("  ", a, n) for a, n in apps.most_common(12)]
print("stopped screen -> screen in front:"); [print("  ", *k, n) for k, n in pairs.most_common(12)]
