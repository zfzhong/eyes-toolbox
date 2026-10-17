import glob, gzip, collections, pandas as pd, os
A = {"Activity Resumed", "Activity Paused", "Activity Stopped"}
tot = collections.Counter(); classes = collections.Counter(); pat = collections.Counter(); ex = []; devs = collections.Counter()
for f in sorted(glob.glob(os.path.expanduser("~/serveraws/media/eyes/days/*/*.csv.gz"))):
    try: d = pd.read_csv(f, usecols=["app_package_name", "app_class_name", "interaction_type", "event_timestamp", "timezone"], low_memory=False)
    except Exception: continue
    d = d[d.interaction_type.isin(A) & (d.app_package_name == "com.android.chrome")].sort_values("event_timestamp", kind="stable")
    if not len(d): continue
    dev = f.split("/")[-2][:8]
    front = None; paused = collections.Counter()      # chrome class in front; chrome classes Paused-not-Stopped
    rows = d.to_dict("records")
    for i, r in enumerate(rows):
        e, c = r["interaction_type"], str(r["app_class_name"]); classes[(e, c)] += 1; tot[e] += 1
        if e == "Activity Resumed": front = c
        elif e == "Activity Paused":
            paused[c] += 1
            if front == c: front = None
        else:
            if front is not None:                      # a chrome Stopped while a chrome screen is in front
                k = ("same class" if front == c else "other class") + (", its Paused before" if paused[c] > 0 else ", NO Paused")
                pat[k] += 1; devs[dev] += 1
                if len(ex) < 6 or (k.endswith("NO Paused") and len(ex) < 10):
                    ex.append((dev, r["timezone"], [(pd.to_datetime(x["event_timestamp"], unit="ms", utc=True).tz_convert(r["timezone"]).strftime("%m-%d %H:%M:%S.%f")[:-3], x["interaction_type"][9:], str(x["app_class_name"]).split(".")[-1]) for x in rows[max(i - 5, 0):i + 3]]))
            if paused[c] > 0: paused[c] -= 1
print("chrome activity events:", dict(tot))
print("Stopped of chrome while a chrome screen is in front:", dict(pat), "by device:", dict(devs))
print("classes:"); [print("  ", k, v) for k, v in classes.most_common(15)]
for dev, tz, seq in ex[:8]:
    print("\n", dev, tz); [print("    ", *s) for s in seq]
