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

FAIL_DOUBLE = "stopped, a double-resumed screen never Paused"
INFERABLE = {FAIL_RESUMED: "Activity Paused", FAIL_PAUSED: "Activity Resumed", FAIL_DOUBLE: "Activity Paused"}
# Not inferable, but marked (David, 10-17): a kill or a lost Paused -> PausedOrKilled(infer) just before the Stopped; a
# Stopped with nothing to stop -> Stopped(unmatched) (a real event without a partner; the front screen is not affected).

def walk(idx, nm, pk, lead=("Activity Stopped",), stop_at_fail=False, inferred=None):
    """Walk the app events idx (indexes into nm / pk) in order. Returns (n, fails): n = events that follow before the
    first failure (len(idx) if none); fails = [(index, kind, app)] (all of them, construction going on after each, unless
    stop_at_fail). lead: event names accepted before the first Resumed (screens opened before the walk began).
    inferred (a list, optional) receives the events the chain infers (David, 10-17: "Paused(infer), Resumed(infer),
    Stopped(infer)", no timestamp): (after index, before index, event, app) - the event lies between those two events:
      FAIL_RESUMED  X never Paused before Y Resumed       -> Paused(infer) of X, after X's last event, before Y's Resumed
      FAIL_PAUSED   X Paused but not in front               -> Resumed(infer) of X, after the last event before it, before it
      FAIL_DOUBLE   X Resumed twice, then a Stopped with no Paused screen
                                                          -> Paused(infer) of X's older screen, before X's next Resumed
    A kill (C8) or a Stopped with nothing to stop has two readings and is not inferred."""
    q = collections.defaultdict(list)                  # app -> entries {"s": "R" | "P", "n": position of its Resumed}
    pending = set()                                    # apps whose R entry must Pause before the next Resumed of another app
    pend_at = {}                                       # app -> position of the Resumed that made it pending (the hand-over)
    seen = set(); seen_r = False; fails = []; first_fail = None; last = {}; lastpos = {}; credit = collections.Counter()
    pos = collections.defaultdict(list)                # app -> positions of its Resumed / Paused in idx
    rpos = collections.defaultdict(list)               # app -> positions of its Resumed
    for n, k in enumerate(idx):
        if nm[k] != "Activity Stopped": pos[pk[k]].append(n)
        if nm[k] == "Activity Resumed": rpos[pk[k]].append(n)
    def next_rp(y, n):                                 # the next Resumed / Paused of app y after position n
        P = pos[y]; j = bisect.bisect_right(P, n)
        return nm[idx[P[j]]] if j < len(P) else None
    def next_r(y, n):                                  # position of app y's next Resumed after position n
        P = rpos[y]; j = bisect.bisect_right(P, n)
        return P[j] if j < len(P) else None
    nxt = {}; later = [None] * len(idx)                # the next Resumed / Paused of the same app (Stopped skipped)
    for n in range(len(idx) - 1, -1, -1):
        later[n] = nxt.get(pk[idx[n]])
        if nm[idx[n]] != "Activity Stopped": nxt[pk[idx[n]]] = nm[idx[n]]
    def infer(after_n, before_n, ev, app):
        if inferred is not None:
            inferred.append((idx[after_n] if after_n is not None and after_n >= 0 else None, idx[before_n], ev, app))
    st = lambda Q, s: [e for e in Q if e["s"] == s]
    for n, k in enumerate(idx):
        e, x = nm[k], pk[k]; Q = q[x]; why = None
        if e == "Activity Resumed":
            seen_r = True
            for y in list(pending):
                if y != x:
                    R = st(q[y], "R")
                    if R and next_rp(y, n) == "Activity Paused":
                        continue                       # still Resumed under x, its Paused comes later (stays pending)
                    if R:
                        h = pend_at.get(y, n - 1)     # Paused(infer) lost by the hand-over Resumed, which reveals it
                        fails.append((k, FAIL_RESUMED, y)); infer(h - 1 if h > 0 else None, h, "Activity Paused", y)
                        R[0]["s"] = "P"                # Paused(infer): the screen goes on to its Stopped
                    pending.discard(y)
            for y, Qy in q.items():
                if y != x and st(Qy, "R") and y not in pending: pending.add(y); pend_at[y] = n
            P = st(Q, "P")
            if P:                                      # returning screen, or a new one: decided later. If a Stopped
                P[-1]["s"] = "R"; P[-1]["n"] = n       # comes with no P entry, it was a new screen after all
                credit[x] += 1
            else: Q.append({"s": "R", "n": n})
            seen.add(x)
        elif e == "Activity Paused":
            R = st(Q, "R")
            if R: R[0]["s"] = "P"; pending.discard(x)
            elif not seen_r and e in lead: Q.append({"s": "P", "n": n})
            elif last.get(x) == "Activity Paused": pass   # written twice (S8): nothing of x between the two
            else:
                why = FAIL_PAUSED; Q.append({"s": "P", "n": n})
                for y, Qy in q.items():                # Resumed(infer) of x took the front: an app still in front whose
                    Ry = st(Qy, "R")                   # next event is a Resumed (not its Paused) lost its Paused here
                    if y != x and Ry and next_rp(y, n) != "Activity Paused":
                        infer(n - 1, n, "Activity Paused", y); Ry[0]["s"] = "P"; pending.discard(y)
                infer(n - 1, n, "Activity Resumed", x)
            seen.add(x)
        else:
            P, R = st(Q, "P"), st(Q, "R")
            if P: Q.remove(P[0])
            elif credit[x] > 0: credit[x] -= 1        # the reused screen was a new one; this is the old one's Stopped
            elif (not seen_r and e in lead) or x not in seen: pass
            elif len(R) >= 2:                          # two screens Resumed, none Paused: the older one's Paused is lost
                why = FAIL_DOUBLE; old = R[0]; Q.remove(old)
                nr = next_r(x, old["n"]); infer(old["n"], nr if nr is not None and nr <= n else n, "Activity Paused", x)
            elif R and later[n] == "Activity Paused": pass
            elif last.get(x) == "Activity Stopped": pass   # written twice (S8): nothing of x between the two
            elif R:
                why = FAIL_KILL; Q.remove(R[0]); pending.discard(x); infer(lastpos.get(x), n, "PausedOrKilled", x)
            else: why = FAIL_STRAY; infer(n, n, "Stopped(unmatched)", x)
            seen.add(x)
        last[x] = e; lastpos[x] = n
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
        "dialog over YouTube, both its Resumed and YouTube's Paused lost": ([("R","y"),("P","d"),("R","y"),("S","d"),("P","y"),("S","y")], [FAIL_PAUSED]),
        "4103_C01 home screen: R P R S R S P S (a Paused lost)": ([("R","h"),("P","h"),("R","h"),("S","h"),("R","h"),("S","h"),("P","h"),("R","c"),("S","h"),("R","y")], [FAIL_DOUBLE]),
    }
    ok = True
    for name, (seq, want) in T.items():
        n, f = run(seq); got = [w for _, w, _ in f]
        print(("ok  " if got == want else "FAIL"), name, got); ok &= got == want
    return ok

if __name__ == "__main__":
    import sys; sys.exit(0 if _test() else 1)
