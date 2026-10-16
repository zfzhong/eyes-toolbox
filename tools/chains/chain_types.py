"""chain_types.py <category folder>: build chains of triplets and sort them into complete / no start / no end / no start-end.
Triplet = one act_one block (Resumed -> Paused -> Stopped of one screen). Two triplets are linked when the next one's
Resumed comes within LINK seconds of this one's Paused (either order: Android may log the Resumed first).
A chain is a maximal run of linked triplets.
  start  the chain's first triplet has a real Resumed (not MissingActivityResumed)
  end    the chain's last triplet has a real Paused (the app left the front); its Stopped is reported apart.
         A chain with a screen-off, shutdown or boot inside it has no end: Android pauses the app in front at the
         screen-off, so its real end was lost and the Paused that closes it came later (4094_C01: "complete" chains of
         153 h and 720 h). Such chains are flagged "spans". A silence alone does not break a chain: a game or video in
         front logs nothing for a long time (Aizhong's Delta Force, 48 min); its length is reported as max_silence_s.
Writes <folder>/_review/chains_<pid>.csv and chain_types.tsv."""
import sys, os, glob
import numpy as np, pandas as pd
LINK = 1.0
SILENCE = 1800
RESET = {"Screen Non-interactive", "Unknown importance: 16", "Device Shutdown", "Unknown importance: 26", "Device Startup", "Unknown importance: 27"}
REAL_R = {"Activity Resumed", "Move to Foreground"}
REAL_P = {"Activity Paused", "Move to Background", "MatchingPreviousBlock", "MatchingCurrentBlock"}
REAL_S = {"Activity Stopped", "Unknown importance: 23"}
folder = os.path.abspath(sys.argv[1]); P = os.path.join(folder, "processed"); out = os.path.join(folder, "_review")
ts = lambda s: pd.to_datetime(s, utc=True, format="ISO8601", errors="coerce").astype("int64").to_numpy() / 1e9
summary = []
for f in sorted(glob.glob(os.path.join(P, "*_act_one.csv"))):
    pid = os.path.basename(f).split("_Chronicle")[0]
    a = pd.read_csv(f)
    r, p = ts(a.resume_time), ts(a.pause_time)
    r[a.resume_time.isna().to_numpy()] = np.nan; p[a.pause_time.isna().to_numpy()] = np.nan
    a["r"], a["p"] = r, p
    a["has_r"] = a.resume_event.isin(REAL_R) & ~np.isnan(r)
    a["has_p"] = a.pause_event.isin(REAL_P) & ~np.isnan(p)
    a["has_s"] = a.stop_event.isin(REAL_S)
    a["t0"] = np.where(np.isnan(r), p, r)
    a = a[~np.isnan(a.t0)].sort_values("t0", kind="mergesort").reset_index(drop=True)
    # link: walk in time order; a triplet joins the open chain when its Resumed is within LINK of the chain's last Paused
    chains = []; cur = None
    for i, b in a.iterrows():
        if cur is not None and b.has_r and cur["last_p"] is not None and abs(b.r - cur["last_p"]) <= LINK:
            cur["n"] += 1; cur["apps"].append(b.app_package_name)
        else:
            if cur is not None: chains.append(cur)
            cur = dict(start=bool(b.has_r), t0=b.t0, n=1, apps=[b.app_package_name])
        cur["end"] = bool(b.has_p); cur["stop"] = bool(b.has_s); cur["t1"] = b.p if b.has_p else (b.r if b.has_r else b.t0)
        cur["last_p"] = b.p if b.has_p else None
    if cur is not None: chains.append(cur)
    C = pd.DataFrame(chains)
    ev = pd.read_csv(f.replace("_act_one.csv", ".csv"), usecols=["interaction_type", "event_timestamp"], low_memory=False)
    et = np.sort(ts(ev.event_timestamp))
    rt = np.sort(ts(ev.event_timestamp[ev.interaction_type.isin(RESET)]))
    gap_t = et[:-1][np.diff(et) >= SILENCE]                          # start of each long silence
    def inside(x, a, b):
        i = np.searchsorted(x, a + LINK, "left"); return i < len(x) and x[i] < b - LINK
    C["spans"] = [inside(rt, a, b) for a, b in zip(C.t0, C.t1)]
    def max_quiet(a, b):
        i, j = np.searchsorted(et, a, "left"), np.searchsorted(et, b, "right")
        x = et[i:j]; return float(np.diff(x).max()) if len(x) > 1 else 0.0
    C["max_silence_s"] = [round(max_quiet(a, b), 1) for a, b in zip(C.t0, C.t1)]
    C.loc[C.spans, "end"] = False
    C["type"] = np.select([C.start & C.end, ~C.start & C.end, C.start & ~C.end], ["complete", "no start", "no end"], "no start-end")
    C["dur_s"] = (C.t1 - C.t0).clip(lower=0)
    C["first_app"] = C.apps.str[0]; C["last_app"] = C.apps.str[-1]
    C.drop(columns=["apps", "last_p"]).to_csv(os.path.join(out, f"chains_{pid}.csv"), index=False)
    n = C.type.value_counts(); h = C.groupby("type").dur_s.sum() / 3600
    row = dict(pid=pid, chains=len(C), spans=int(C.spans.sum()))
    for k in ["complete", "no start", "no end", "no start-end"]:
        row[k] = int(n.get(k, 0)); row[k + " h"] = round(float(h.get(k, 0)), 1)
    row["complete %"] = round(100 * row["complete"] / len(C), 1); row["complete time %"] = round(100 * row["complete h"] / max(C.dur_s.sum() / 3600, 1e-9), 1)
    summary.append(row)
S = pd.DataFrame(summary); S.to_csv(os.path.join(out, "chain_types.tsv"), sep="\t", index=False)
print(S.to_string(index=False))
tot = S[["chains", "spans", "complete", "no start", "no end", "no start-end"]].sum()
print("\nALL:", tot.to_dict(), " complete %.1f%%" % (100 * tot["complete"] / tot["chains"]))
