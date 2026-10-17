"""chain_core.py: the activity logical chain, built with one FIFO queue of triplets per app (David, 10-16: "we can have a
triplet FIFO queue to match the resumed->paused->stopped triplet"; "this FIFO queue helps us construct the activity
logical chain"). Event order only, no time thresholds. Used by screen_blocks.py and block_fails.py.

Per app, a queue of open triplets, oldest first; each entry is "R" (Resumed, not yet Paused) or "P" (Paused, not yet
Stopped). No size limit (EyesApp: 98.6% of moments have 3 or fewer, up to 10).
  Resumed(x)  reuse x's newest P entry if there is one (a returning screen: the screen on top closed, or a small window
              back to full screen), otherwise append an R entry. Without class names a reuse may in fact be a new screen
              (S7): if a Stopped of x later finds no P entry, it takes that reuse back (the old screen's Stopped). Two Resumed of one app in a row are fine (S8, S9).
              Every other app's R entry becomes "pending": its Paused must come before the next Resumed of another app
              (hand-over R(B) before P(A)), unless its own next event is still that Paused (it stayed Resumed under
              the other app, e.g. the home screen shown during a gesture; EyesApp, Xiaomi); otherwise that Paused was
              lost -> failure.
  Paused(x)   completes x's oldest R entry -> P. None: before the first Resumed of the walk it is a screen opened before the
              start (accepted); right after a Paused of x, nothing of x between: written twice (S8; accepted); otherwise
              x was not in front -> failure (a Resumed lost).
  Stopped(x)  completes x's oldest P entry (FIFO; EyesApp: the oldest in 96%). None:
                - before the first Resumed of the walk, or x not seen yet: its Paused came before the start (accepted);
                - x has an R entry whose Paused comes later: an earlier screen's Stopped (S7; accepted);
                - x has an R entry that never Pauses: a kill (C8) or a lost Paused -> failure;
                - right after a Stopped of x, nothing of x between: written twice (S8; accepted);
                - otherwise: a Stopped with nothing to stop (a lost Paused) -> failure.
Truth scenarios (claude/scenarios.md S7-S9) and the 4103_C01 Chrome trace are the tests (run this file)."""
import collections, bisect

FAIL_RESUMED = "resumed, previous app never Paused"
FAIL_PAUSED = "paused, app not in front"
FAIL_KILL = "stopped in front, no Paused"
FAIL_STRAY = "stopped twice"

def walk(idx, nm, pk, lead=("Activity Stopped",), stop_at_fail=False):
    """Walk the app events idx (indexes into nm / pk) in order. Returns (n, fails): n = events that follow before the
    first failure (len(idx) if none); fails = [(index, kind, app)] (all of them, construction going on after each, unless
    stop_at_fail). lead: event names accepted before the first Resumed (screens opened before the walk began)."""
    q = collections.defaultdict(list)                  # app -> entries "R" / "P", oldest first
    pending = set()                                    # apps whose R entry must Pause before the next Resumed of another app
    seen = set(); seen_r = False; fails = []; first_fail = None; last = {}; credit = collections.Counter()
    pos = collections.defaultdict(list)                # app -> positions of its Resumed / Paused in idx
    for n, k in enumerate(idx):
        if nm[k] != "Activity Stopped": pos[pk[k]].append(n)
    def next_rp(y, n):                                 # the next Resumed / Paused of app y after position n
        P = pos[y]; j = bisect.bisect_right(P, n)
        return nm[idx[P[j]]] if j < len(P) else None
    nxt = {}; later = [None] * len(idx)                # the next Resumed / Paused of the same app (Stopped skipped)
    for n in range(len(idx) - 1, -1, -1):
        later[n] = nxt.get(pk[idx[n]])
        if nm[idx[n]] != "Activity Stopped": nxt[pk[idx[n]]] = nm[idx[n]]
    for n, k in enumerate(idx):
        e, x = nm[k], pk[k]; Q = q[x]; why = None
        if e == "Activity Resumed":
            seen_r = True
            for y in list(pending):
                if y != x:
                    if "R" in q[y] and next_rp(y, n) == "Activity Paused":
                        continue                       # still Resumed under x, its Paused comes later (stays pending)
                    if "R" in q[y]:
                        why = FAIL_RESUMED; fails.append((k, why, y))
                        q[y] = [s for s in q[y] if s != "R"]   # its Paused is lost; the screen is gone
                    pending.discard(y)
            for y, Qy in q.items():
                if y != x and "R" in Qy: pending.add(y)
            if "P" in Q:                               # returning screen, or a new one: decided later. If a Stopped
                Q[len(Q) - 1 - Q[::-1].index("P")] = "R"   # comes with no P entry, it was a new screen after all
                credit[x] += 1
            else: Q.append("R")
            seen.add(x); why = None
        elif e == "Activity Paused":
            if "R" in Q: Q[Q.index("R")] = "P"; pending.discard(x)
            elif not seen_r and e in lead: Q.append("P")
            elif last.get(x) == "Activity Paused": pass   # written twice (S8): nothing of x between the two
            else: why = FAIL_PAUSED; Q.append("P")
            seen.add(x)
        else:
            if "P" in Q: Q.remove("P")
            elif credit[x] > 0: credit[x] -= 1        # the reused screen was a new one; this is the old one's Stopped
            elif (not seen_r and e in lead) or x not in seen: pass
            elif "R" in Q and later[n] == "Activity Paused": pass
            elif last.get(x) == "Activity Stopped": pass   # written twice (S8): nothing of x between the two
            elif "R" in Q: why = FAIL_KILL; Q.remove("R"); pending.discard(x)
            else: why = FAIL_STRAY
            seen.add(x)
        last[x] = e
        if why:
            fails.append((k, why, x))
        if fails and first_fail is None:
            first_fail = n
            if stop_at_fail: return n, fails
    return (len(idx) if first_fail is None else first_fail), fails

def _test():
    def run(seq, lead=("Activity Stopped",)):
        nm = [{"R": "Activity Resumed", "P": "Activity Paused", "S": "Activity Stopped"}[c] for c, _ in seq]; pk = [a for _, a in seq]
        return walk(list(range(len(seq))), nm, pk, lead)
    T = {  # name: (sequence of (event, app), expected failure kinds)
        "S7 three screens R P R P R S S P S": ([("R","c"),("P","c"),("R","c"),("P","c"),("R","c"),("S","c"),("S","c"),("P","c"),("R","y"),("S","c")], []),
        "S8 double resumes, same screen": ([("R","w"),("R","h"),("P","w"),("R","h"),("S","w"),("S","w"),("P","h"),("S","h"),("P","h"),("S","h")], []),
        "S9 double resumes, two screens": ([("R","q"),("R","q"),("P","q"),("R","h"),("S","q"),("P","q"),("S","q")], []),
        "4103_C01 Chrome (YouTube after)": ([("R","c"),("S","l"),("P","c"),("R","c"),("P","c"),("R","c"),("S","c"),("S","c"),("P","c"),("R","y"),("S","c")], []),
        "returning screen (Douyin feed)": ([("R","d"),("P","d"),("R","d"),("P","d"),("R","d"),("S","d"),("P","d"),("R","h"),("S","d")], []),
        "small window back to full screen": ([("R","y"),("P","y"),("R","h"),("P","h"),("R","y"),("S","h")], []),
        "hand-over, next Resumed first": ([("R","a"),("R","b"),("P","a"),("S","a"),("P","b"),("S","b")], []),
        "Paused written twice (S8, OPPO)": ([("R","a"),("P","a"),("P","a"),("R","b"),("S","a")], []),
        "three screens then screen-off (4104_C01 Chronicle app)": ([("R","c"),("P","c"),("R","c"),("P","c"),("R","c"),("S","c"),("S","c")], []),
        "kill (C8)": ([("R","a"),("S","a"),("R","b")], [FAIL_KILL]),
        "app stays Resumed under a home gesture": ([("R","a"),("R","h"),("P","h"),("S","h"),("R","h"),("P","a"),("S","a")], []),
        "lost Paused": ([("R","a"),("R","b"),("P","b"),("R","c")], [FAIL_RESUMED]),
        "lost Resumed": ([("R","a"),("P","a"),("S","a"),("P","b")], [FAIL_PAUSED]),
    }
    ok = True
    for name, (seq, want) in T.items():
        n, f = run(seq); got = [w for _, w, _ in f]
        print(("ok  " if got == want else "FAIL"), name, got); ok &= got == want
    return ok

if __name__ == "__main__":
    import sys; sys.exit(0 if _test() else 1)
