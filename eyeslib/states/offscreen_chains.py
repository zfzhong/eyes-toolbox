"""App events while the screen is confirmed off: label them, and write a clean log for usage.

Pattern book B10 / B12 (David, 10-13):
  background  : a chain that starts and ends completely inside a confirmed screen-off period
                (single blip, logic chain, proximity chain). Never visible: not use.
  wakeup      : a chain still running when the screen comes on, that started <= WAKE_LEAD_S
                before it. The app turned the screen on (alarm, call, reminder); its use starts
                at Screen Interactive, not before.
  unsure      : still running at the screen-on but started earlier (long lead), or a chain that
                does not follow Android's order (broken). Left as it is, for review.

Confirmed screen-off period: Screen Non-interactive -> the next Screen Interactive, with no
second Non-interactive, Keyguard Hidden, User Interaction, Device Shutdown / Startup between,
and no Android Auto projection (gearhead foreground service) overlapping. Periods whose screen
state is unsure are not touched. Lock-screen feeds (B8) are not part of chains.

Chains follow Android's transition order: a chain starts at a Resumed while nothing is in
front; app1 hands over to app2 as Resumed1 -> Paused1 -> Resumed2 -> Stopped1; it ends when
every app of it is Stopped and nothing is in front.

Outputs, next to the input <stem>.csv (a *_reordered.csv log):
  <stem>_offscreen.csv : one row per labelled event (row, time, app, event, label, chain, kind)
  <stem>_clean.csv     : the log with background events removed and each wake-up chain's
                         Resumed moved to just after the Screen Interactive (original time kept
                         in column original_timestamp). Events before the screen-on of a
                         wake-up chain are removed. Everything else is unchanged.
Usage: python -m eyeslib.states.offscreen_chains <stem>_reordered.csv [...]
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from eyeslib.core.event_classes import canonical_name

FEEDS = {"com.metro.minus1", "com.metropcs.metrozone"}
BREAK = {"Screen Non-interactive", "Keyguard Hidden", "User Interaction",
         "Device Shutdown", "Device Startup"}
APP = {"Activity Resumed", "Activity Paused", "Activity Stopped"}
CAR = "com.google.android.projection.gearhead"
CLOSE_MARGIN_MS = 2000      # a chain must end this long before the screen-on to be "background"
WAKE_LEAD_S = 5             # wake-up: started at most this long before the screen-on


def projections(it, pk, t):
    out, st = [], None
    for i in np.where((pk == CAR) & np.isin(it, ["Foreground Service Start", "Foreground Service Stop"]))[0]:
        if it[i] == "Foreground Service Start" and st is None:
            st = t[i]
        elif it[i] == "Foreground Service Stop" and st is not None:
            out.append((st, t[i])); st = None
    if st is not None:
        out.append((st, t[-1]))
    return out


def confirmed_off_periods(it, t, proj):
    """[(a, b)] row indices: a = Screen Non-interactive, b = the next Screen Interactive."""
    scr = np.where(np.isin(it, ["Screen Interactive", "Screen Non-interactive"]))[0]
    out = []
    for a, b in zip(scr, scr[1:]):
        if it[a] != "Screen Non-interactive" or it[b] != "Screen Interactive":
            continue
        if np.isin(it[a + 1:b], list(BREAK)).any():
            continue
        if any(x <= t[b] and y >= t[a] for x, y in proj):
            continue
        out.append((a, b))
    return out


def chains(rows, it, pk, t):
    """rows: app-event row indices of one period, in log order. Returns a list of dicts."""
    out, ch, front = [], None, None
    for i in rows:
        ty, p = it[i], pk[i]
        if ch is None:
            if ty == "Activity Resumed":
                ch = dict(rows=[i], st={p: "R"}, hand=0, broken=False)
                front = p
            continue                    # closing events of the session before the screen-off
        ch["rows"].append(i)
        if ty == "Activity Resumed":
            if front is not None and front != p:
                ch["broken"] = True
            elif front is None:
                if any(v == "P" for v in ch["st"].values()):
                    ch["hand"] += 1
                else:
                    ch["broken"] = True
            ch["st"][p] = "R"; front = p
        elif ty == "Activity Paused":
            if p == front:
                ch["st"][p] = "P"; front = None
            elif p not in ch["st"]:
                ch["broken"] = True
        elif ty == "Activity Stopped":
            if ch["st"].get(p) == "P":
                ch["st"][p] = "S"
            elif p not in ch["st"]:
                ch["broken"] = True
            if front is None and all(v == "S" for v in ch["st"].values()):
                ch["done"] = True; ch["front"] = None
                out.append(ch); ch = None; front = None
    if ch is not None:
        ch["done"] = False; ch["front"] = front
        out.append(ch)
    return out


def label(df):
    # canonical names: older Chronicle files log Move to Foreground / Background and
    # "Unknown importance: 23 / 15 / 16 / 18 ..." instead of the named events
    names = {v: canonical_name(v) for v in df["interaction_type"].astype(str).unique()}
    it = df["interaction_type"].astype(str).map(names).values
    pk = df["app_package_name"].astype(str).values
    t = (pd.to_datetime(df["event_timestamp"], format="mixed", utc=True, errors="coerce")
         .astype("int64") // 10**6).values
    proj = projections(it, pk, t)
    labels = []          # (row, label, chain_no, kind, screen_on_row)
    n_chain = 0
    for a, b in confirmed_off_periods(it, t, proj):
        rows = [i for i in range(a + 1, b) if it[i] in APP and pk[i] not in FEEDS]
        for ch in chains(rows, it, pk, t):
            n_chain += 1
            napps = len(ch["st"])
            kind = "single" if napps == 1 else "logic"
            t0, t1 = t[ch["rows"][0]], t[ch["rows"][-1]]
            if ch["broken"]:
                lab = "unsure_broken"
            elif ch["done"] and t[b] - t1 >= 0:
                lab = "background"           # started and ended inside the off period
            elif (t[b] - t0) / 1000 <= WAKE_LEAD_S:
                lab = "wakeup"
            else:
                lab = "unsure_long_lead"
            for i in ch["rows"]:
                labels.append((i, lab, n_chain, kind, b, ch.get("front")))
    lab = pd.DataFrame(labels, columns=["row", "label", "chain", "kind", "screen_on_row", "front"])
    # proximity: background chains that follow one another within 1 s (kept as one id)
    return lab


def clean(df, lab):
    out = df.copy()
    out["original_timestamp"] = ""
    drop = set(lab.loc[lab.label == "background", "row"])
    moves = []                                  # (resumed row, screen_on row)
    for c, g in lab[lab.label == "wakeup"].groupby("chain"):
        front = g["front"].iloc[0]
        keep = None
        if isinstance(front, str):
            res = g[(df.loc[g.row, "interaction_type"].astype(str).map(canonical_name).values == "Activity Resumed")
                    & (df.loc[g.row, "app_package_name"].astype(str).values == front)]
            if len(res):
                keep = int(res.row.iloc[-1])
        for r in g.row:
            if r != keep:
                drop.add(r)
        if keep is not None:
            moves.append((keep, int(g.screen_on_row.iloc[0])))
    order = [i for i in range(len(df)) if i not in drop]
    moved = {k for k, _ in moves}
    after = {}
    for k, s in moves:
        after.setdefault(s, []).append(k)
    final = []
    for i in order:
        if i in moved:
            continue
        final.append(i)
        for k in after.get(i, []):
            final.append(k)
    for k, s in moves:
        out.at[k, "original_timestamp"] = out.at[k, "event_timestamp"]
        out.at[k, "event_timestamp"] = out.at[s, "event_timestamp"]
    return out.iloc[final].reset_index(drop=True)


def main(paths):
    for p in paths:
        p = Path(p)
        df = pd.read_csv(p)
        lab = label(df)
        rows = lab.row.values
        detail = pd.DataFrame({
            "row": rows,
            "event_timestamp": df.loc[rows, "event_timestamp"].values,
            "app_package_name": df.loc[rows, "app_package_name"].values,
            "interaction_type": df.loc[rows, "interaction_type"].values,
            "label": lab.label.values, "chain": lab.chain.values, "kind": lab.kind.values,
            "screen_on_timestamp": df.loc[lab.screen_on_row.values, "event_timestamp"].values,
        })
        stem = p.with_suffix("")
        detail.to_csv(f"{stem}_offscreen.csv", index=False)
        clean(df, lab).to_csv(f"{stem}_clean.csv", index=False)
        ch = lab.drop_duplicates("chain")
        print(f"{p.name}: {len(df)} events; chains {dict(ch.label.value_counts())}; "
              f"events relabelled {len(lab)}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    main(sys.argv[1:])
