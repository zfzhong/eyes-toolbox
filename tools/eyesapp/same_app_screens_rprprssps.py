import glob, collections, pandas as pd, os
A = {"Activity Resumed": "R", "Activity Paused": "P", "Activity Stopped": "S"}
want = "RPRPRSSPS"; hits = []; per = collections.Counter()
for f in sorted(glob.glob(os.path.expanduser("~/serveraws/media/eyes/days/*/*.csv.gz"))):
    try: d = pd.read_csv(f, usecols=["app_package_name", "app_class_name", "interaction_type", "event_timestamp", "timezone"], low_memory=False)
    except Exception: continue
    d = d[d.interaction_type.isin(A)].sort_values("event_timestamp", kind="stable").reset_index(drop=True)
    if not len(d): continue
    dev = f.split("/")[-2]
    # per package: the package's own consecutive activity events (other apps may sit between)
    for p, g in d.groupby("app_package_name"):
        code = "".join(A[x] for x in g.interaction_type); idx = list(g.index)
        s = 0
        while True:
            j = code.find(want, s)
            if j < 0: break
            seg = idx[j:j + len(want)]
            w = d.loc[seg[0]:seg[-1]]
            hits.append((dev, os.path.basename(f)[:10], p, g.timezone.iloc[0], w)); per[p] += 1; s = j + 1
print(len(hits), "matches;", per.most_common(10))
import pickle; pickle.dump([(a, b, c, t, w.to_dict("records")) for a, b, c, t, w in hits], open("/tmp/rprpr.pkl", "wb"))
for dev, day, p, tz, w in hits[:6]:
    print("\n", dev[:8], day, p, tz)
    for r in w.itertuples():
        print("   ", pd.to_datetime(r.event_timestamp, unit="ms", utc=True).tz_convert(tz).strftime("%H:%M:%S.%f")[:-3], r.interaction_type, r.app_package_name, str(r.app_class_name).split(".")[-1], "" if r.app_package_name == p else "(other app)")
