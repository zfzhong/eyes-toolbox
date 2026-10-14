"""
Device states (see the manual, "Device State Analysis").

The timeline of a log is cut at every logged event. Each interval between two
consecutive events gets the SET of device states it could be in:

    Off      the device is shut down          (bit 1)
    Idle     on, screen off                    (bit 2)
    Active   on, screen on                     (bit 4)

so there are seven labels: Off, Idle, Active, Unsure OI, Unsure IA, Unsure OA and
Unsure 3 (any of the three). Evidence only removes states from a set, never adds
them back, so a weak rule cannot overturn a strong one.

Two layers (strict, likely) are computed side by side.

Step 1 decides, for every quiet stretch (no event at all) of at least
TOLERANCE_SECONDS, whether the device was Off or On, from the events around it,
and records which sign decided (off_sign / on_sign):

    Off signs  shutdown_before, startup_after, shutdown_startup, unlocked_after
               (logged boot events: confirmed, both layers);
               boot_signature (likely layer; wins over On signs, and the
               stretch is listed as a conflict);
               (system_pausefirst_after, a system app pausing without having
               started, was tried and discarded as too weak);
               long_quiet (likely layer: a quiet stretch longer than
               LONG_QUIET_OFF_SECONDS, 6 h, is Off whatever On sign it has;
               when the screen was not logged off going into it, the stretch
               is also listed for review, since it could hide screen time).
    On signs   normal_unlock (the next Keyguard Hidden comes with no User
               Unlocked or Device Startup up to 60 s after it, compared by
               time); app_continuity (below).

    strict   Off only by logged boot events; not Off when an On sign exists;
             otherwise the stretch may still be Off.
    likely   also Off by boot signature, or by system pause-first when no On
             sign exists; every other stretch is not Off.

Boot signature. A confirmed boot is a Device Startup or User Unlocked (merged
within SIG_SAME_BOOT_SECONDS). Its items are the heartbeat-class
"event name | package" pairs within BOOT_BURST_SECONDS of the marker. A device's
core is the items seen in at least SIG_CORE_SHARE of its boots; it is used when
the device has at least SIG_MIN_BOOTS boots and SIG_MIN_ITEMS core items,
otherwise the pooled core (items in at least SIG_POOL_SHARE of the device
cores) is used. The score of a stretch is the share of the core seen in the
BOOT_BURST_SECONDS after it; the cut is SIG_SCORE (own) or SIG_POOL_SCORE
(pooled). In A1, leave-one-out, the own signature finds 92.4% of 2,381 logged
boots and fires on 9 of 258,352 ordinary wake-ups.

Screen evidence (both layers). A "screen run" lasts from one screen event to the
next (Screen Interactive, Screen Non-interactive, Keyguard Hidden when the screen
was not on, or a shutdown/boot, which reset the state):

    screen_on            on, closed by a screen off: Active
    screen_on_active     on, the screen-off was not logged (the next screen event
                         is another screen on, a boot or the end of the log):
                         Active up to the last usage event of the run
    screen_on_tail       ... and after it: Idle or Active (the screen went off
                         somewhere in it, or the person kept watching)
    screen_on_tail_idle  ... and from SCREEN_TAIL_IDLE_SECONDS (5 min) after that last
                         usage event, with only background events since: Idle
    screen_on_end_lost   ... a silence of more than 30 min that starts at that last usage
                         event: the use ended somewhere inside it, unlogged; no screen time
                         can be granted, so Idle
    screen_on_same_app   a silence of more than 30 min with the screen on, but the same user
                         app is Resumed before it and Paused after it: it stayed in front,
                         the screen stayed on: Active
    screen_off           off, closed by a screen on, boot or shutdown: Idle
    screen_off_lost_on   off, followed by another screen off: the screen-on was
                         not logged: Idle or Active
    screen_off_until_use ... but up to the first usage event after the screen-off the
                         screen was still off: Idle
    background_only      where a screen-on was lost or the screen state is unknown: Idle once
                         only background events for SCREEN_TAIL_IDLE_SECONDS since the last
                         usage event
    screen_unknown       before the first screen event, or after a boot or
                         shutdown until the next one: Idle or Active
    screen_on_long_silence  a silence of more than SCREEN_ON_MAX_SILENCE_SECONDS
                         (30 min) while the screen is logged on: Idle or Active.
                         Screens time out within minutes and apps that hold the
                         screen on still log events now and then, so a longer
                         silence most likely hides a lost screen-off.

Continuity (both layers; only removes Off):

    app_continuity       the last Resumed/Paused before the silence and the first
                         after it belong to the same USER app (NON_USER_APP lists
                         what is not one), as
                         Paused(X) ... Resumed(X) (locked in X, back in X) or
                         Resumed(X) ... Paused(X) (X stayed in front). A reboot
                         restarts at the lock and home screens, so X picking up
                         where it left off shows the device stayed on. In A1, of
                         3,517 logged reboots only 31 (0.9%) look like this, none
                         after 1 h or more off. Only user apps are evidence: not the
                         logger, Android system parts and services, home screens and
                         their feeds, or apps the phone brings to the front by itself
                         (call screen, clock/alarm, Android Auto), since a boot or an
                         alarm can show those without any continuity.
                         A stretch settled this way that is longer than
                         CONTINUITY_REVIEW_SECONDS (30 min) still goes to review.

Off evidence (the dark stretch next to the evidence; the boot window is the
BOOT_BURST_SECONDS before the marker, the same window the session builder uses):

    shutdown_before          Device Shutdown, then the longest silence before the
                             next usage event or boot           Off (both layers)
    startup_after            Device Startup: the longest silence in the window
                             before it                          Off (both layers)
    shutdown_startup         both of the above on the same silence
    unlocked_after           User Unlocked without a Device Startup   Off (likely)
    system_pausefirst_after  a system app (Settings, home screen, System UI, setup
                             wizard, permission controller) paused without having
                             started                                   Off (likely)
The two likely signs need a silence of at least TOLERANCE_SECONDS.

Tolerance. A silence shorter than TOLERANCE_SECONDS (5 min) is never counted as
possibly Off: if that is wrong, it is wrong by at most 5 minutes. (A reboot can be
faster: the fastest logged in A1 took 10.3 s.)
"""
import re

import numpy as np
import pandas as pd

from eyeslib.core.event_classes import canonical_name, event_class

OFF, IDLE, ACTIVE = 1, 2, 4
NOLOG = 8   # "No logging": a long silence with no power marker; the log was lost and the state cannot be told
NOLOG_OFF = NOLOG | OFF   # "No logging, likely off" (reviewer, 2026-10-08): no power marker, 2 days or more
LABELS = {1: "Off", 2: "Idle", 4: "Active", 3: "Unsure OI", 6: "Unsure IA", 5: "Unsure OA", 7: "Unsure 3", 8: "No logging", 9: "No logging, likely off"}
LABEL_ORDER = ["Off", "Idle", "Active", "Unsure OI", "Unsure IA", "Unsure OA", "Unsure 3", "No logging", "No logging, likely off"]

TOLERANCE_SECONDS = 300.0   # silences shorter than this are not counted as possibly Off (manual)
SCREEN_ON_MAX_SILENCE_SECONDS = 1800.0   # longer silences with the screen logged on: Idle or Active
BOOT_BURST_SECONDS = 60.0   # same window as eyeslib.usage.build_sessions

SYSTEM_BOOT_APP = re.compile(r"(?:launcher|home|^android$|^com\.android\.systemui$|^com\.android\.settings$"
                             r"|setupwizard|permissioncontroller)")
RESETS = {"Device Shutdown", "Device Startup", "User Unlocked", "User Stopped"}
# Not user apps, so not evidence of continuity: the logger; Android system parts and services; home screens and
# their feeds; apps the phone brings to the front by itself (call screen, clock/alarm, Android Auto).
LOCKSCREEN_FEED_APP = re.compile(r"^(?:com\.metro\.minus1|com\.metropcs\.metrozone)$")   # carrier lock-screen / home feeds

NON_USER_APP = re.compile(
    r"(?:^android$|^com\.openlattice\.chronicle$"
    r"|launcher|\.home$|home$|iwawahome|minus1|metrozone|sliide|onlineplus"
    r"|systemui|\.settings$|packageinstaller|permissioncontroller|setupwizard|provision"
    r"|^com\.google\.android\.gms|^com\.google\.android\.gsf|^com\.android\.dreams\.|daydream|screensaver|lockscreen"
    r"|keyguard|aodservice|daemonapp|wssyncmldm|fota|softwareupdate|batterywarning|incallui|deskclock|clockpackage"
    r"|alarmclock|projection\.gearhead|^com\.android\.phone$|^com\.android\.server|^com\.android\.shell$|stk$)")
CONTINUITY_REVIEW_SECONDS = 1800.0   # longer stretches settled by continuity still go to review (David)
SCREEN_TAIL_IDLE_SECONDS = 300.0       # screen-off lost: Idle once only background events for this long after the last usage event (reviewer, 2026-10-01)
LONG_QUIET_SURE_SECONDS = 12 * 3600.0  # a silence this long is Off without review, whatever the screen state before it (reviewer, 2026-10-01)
LONG_QUIET_OFF_SECONDS = 6 * 3600.0  # a quiet stretch longer than this is Off in the likely layer (reviewer's rule, 2026-10-01)
NO_LOGGING_OFF_SECONDS = 48 * 3600.0  # (reviewer, 2026-10-08) a silence of 6 h or more with no power marker is "No logging";
                                      # from 2 days on it is taken as Off (likely): "in reality that is powering off"
LONG_ON_REVIEW_SECONDS = 12 * 3600.0  # On stretches this long go to review: a live phone rarely goes 12 h with no event
                                      # (99% of its waits between heartbeats are under 10.7 h); more likely no data

# Boot signature (manual, "Boot signature"): what a boot phase looks like on a device, learned from its confirmed boots
SIG_MARKERS = ("Device Startup", "User Unlocked")          # a confirmed boot
SIG_NOT_ITEMS = ("Device Startup", "User Unlocked", "Device Shutdown")
SIG_MIN_BOOTS = 5          # a device needs this many confirmed boots for its own signature
SIG_MIN_ITEMS = 5          # ... and its signature at least this many items (with 1-4 items anything can match:
                           # in A1 those caused 271 of 280 false hits)
SIG_CORE_SHARE = 0.8       # an item is in the signature when it is in this share of the device's confirmed boots
SIG_SCORE = 0.8            # a phase is a boot when it holds this share of the device's own signature
SIG_POOL_SHARE = 0.5       # pooled signature: items in the signature of this share of the devices
SIG_POOL_SCORE = 0.5       # ... and the cut-off when a device has to use the pooled signature
SIG_SAME_BOOT_SECONDS = 300.0


def load_events(reordered_csv):
    cols = ["app_package_name", "interaction_type", "event_timestamp"]
    df = pd.read_csv(reordered_csv, usecols=cols, low_memory=False)
    ts = pd.to_datetime(df["event_timestamp"], utc=True, format="ISO8601", errors="coerce")
    df["t"] = ts.dt.as_unit("ns").astype("int64") / 1e9
    df = df[ts.notna()].sort_values("t", kind="mergesort").reset_index(drop=True)
    names = {v: canonical_name(v) for v in df["interaction_type"].unique()}
    df["name"] = df["interaction_type"].map(names)
    df["cls"] = df["name"].map({v: event_class(v) for v in set(names.values())})
    return df[["t", "name", "cls", "app_package_name"]]


RULES = ["screen_on", "screen_on_active", "screen_on_tail", "screen_off", "screen_off_lost_on", "screen_unknown",
         "shutdown_before", "startup_after", "shutdown_startup", "unlocked_after", "system_pausefirst_after",
         "screen_on_long_silence", "app_continuity",      # new rules go at the end: ids stay stable
         "boot_signature", "normal_unlock", "long_quiet", "screen_on_tail_idle", "screen_off_until_use", "background_only", "screen_on_end_lost", "screen_on_same_app",
         "shutdown_unclean_before", "shutdown_unclean_startup", "no_logging"]
CONFIRMED_OFF = {"shutdown_before", "startup_after", "shutdown_startup", "unlocked_after"}   # logged boot events
LIKELY_OFF = {"boot_signature", "system_pausefirst_after", "long_quiet", "shutdown_unclean_before", "shutdown_unclean_startup"}   # inferred
UNCLEAN_OFF = {"shutdown_unclean_before", "shutdown_unclean_startup"}
POWER_OFF_SIGNS = CONFIRMED_OFF | {"boot_signature"} | UNCLEAN_OFF       # the device went off (or restarted) here
SHUTDOWN_CLOSE_SECONDS = 1.5   # clean shutdown: the app in front is Paused / Stopped within this before the Device Shutdown
_R = {r: i for i, r in enumerate(RULES)}


def shutdown_kinds(ev):
    """For each Device Shutdown row: (index, kind). kind is "clean" or "unclean".
    Samsung test phone (2026-10-08): a shutdown from the power menu Pauses and Stops the app in front in the
    shutdown second; after a forced restart Android stamps a Device Shutdown at its last save, closes nothing, and
    everything logged after that save is lost. A small window (Paused, not Stopped) and running services are left
    open by both kinds.
      unclean  an app Resumed since the last screen / boot event and never Paused, or nothing Paused / Stopped
               within SHUTDOWN_CLOSE_SECONDS before the shutdown
      clean    otherwise
    A1 (1,857 shutdowns): clean 1,136; unclean 721 (app left open 252, screen on and nothing closed 286, screen
    already off at the last save 183)."""
    t = ev["t"].to_numpy(); nm = ev["name"].to_numpy(); pk = ev["app_package_name"].astype(str).to_numpy()
    out = []
    reset = np.isin(nm, ["Screen Interactive", "Screen Non-interactive", "Device Startup", "User Unlocked"])
    act = np.isin(nm, ["Activity Resumed", "Activity Paused"])
    close = np.isin(nm, ["Activity Paused", "Activity Stopped"])
    rs = np.where(reset)[0]; ac = np.where(act)[0]; cl = np.where(close)[0]
    for i in np.where(nm == "Device Shutdown")[0]:
        k = np.searchsorted(rs, i) - 1; r0 = rs[k] if k >= 0 else -1
        last = {}
        for j in ac[(ac > r0) & (ac < i)]:
            last[pk[j]] = nm[j]
        open_app = any(v == "Activity Resumed" for v in last.values())
        a = np.searchsorted(cl, i) - 1
        closed = a >= 0 and t[cl[a]] >= t[i] - SHUTDOWN_CLOSE_SECONDS
        out.append((int(i), "unclean" if open_app or not closed else "clean"))
    return out


def screen_runs(nm):
    """[(s, e, state, end_kind)]: intervals s..e-1 share one screen state (on / off / unknown);
    end_kind is what closed the run: on, off, reset (shutdown/boot) or eof."""
    setters = np.where(np.isin(nm, ["Screen Interactive", "Screen Non-interactive", "Keyguard Hidden"] + sorted(RESETS)))[0]
    runs, cur, start = [], "unknown", 0
    for i in setters:
        x = nm[i]
        if x == "Keyguard Hidden":
            if cur == "on":
                continue             # the normal unlock after a screen on
            kind = "on"              # unlocked while the screen was logged off: the screen-on was lost
        elif x == "Screen Interactive":
            kind = "on"
        elif x == "Screen Non-interactive":
            kind = "off"
        else:
            kind = "reset"
        if i > start:
            runs.append((start, i, cur, kind))
        cur, start = ("unknown" if kind == "reset" else kind), i
    if len(nm) - 1 > start:
        runs.append((start, len(nm) - 1, cur, "eof"))
    return runs


def orphan_system_pauses(ev):
    """Indices of Paused events of system apps whose previous Resumed/Paused was not a Resumed."""
    rp = ev[ev["name"].isin(["Activity Resumed", "Activity Paused"])]
    prev = rp["name"].groupby(rp["app_package_name"]).shift()
    orphan = (rp["name"] == "Activity Paused") & (prev != "Activity Resumed")
    sys_app = rp["app_package_name"].astype(str).str.contains(SYSTEM_BOOT_APP)
    return rp.index[orphan & sys_app].to_numpy()


def app_continuity(ev, k, kind="both"):
    """For intervals k (between events k and k+1): True where the last Resumed/Paused at or before
    event k and the first at or after event k+1 are the same user app, as P(X)...R(X) or R(X)...P(X)."""
    k = np.asarray(k)
    nm = ev["name"].to_numpy()
    rp = np.where(np.isin(nm, ["Activity Resumed", "Activity Paused"]))[0]
    if not len(k) or not len(rp):
        return np.zeros(len(k), dtype=bool)
    pkg = ev["app_package_name"].astype(str).to_numpy()
    a = np.searchsorted(rp, k, "right") - 1
    b = np.searchsorted(rp, k + 1, "left")
    ok = (a >= 0) & (b < len(rp))
    ia, ib = rp[np.clip(a, 0, len(rp) - 1)], rp[np.clip(b, 0, len(rp) - 1)]
    sys_app = pd.Series(pkg[ia]).str.contains(NON_USER_APP).to_numpy()      # only user apps are evidence
    pr = (nm[ia] == "Activity Paused") & (nm[ib] == "Activity Resumed")
    rpp = (nm[ia] == "Activity Resumed") & (nm[ib] == "Activity Paused")
    return ok & (pkg[ia] == pkg[ib]) & ~sys_app & (rpp if kind == "in_front" else (pr | rpp))


def event_items(ev):
    """One item per event: 'event name | app package' (what a boot signature is made of)."""
    return np.char.add(np.char.add(ev["name"].to_numpy().astype(str), " | "),
                       ev["app_package_name"].astype(str).to_numpy().astype(str))


def boot_core(ev):
    """(signature items, number of confirmed boots) for one device. A confirmed boot is a Device Startup or a
    User Unlocked (markers closer than SIG_SAME_BOOT_SECONDS are one boot); its phase is the 60 s around it.
    The signature is the items present in at least SIG_CORE_SHARE of the boot phases."""
    t, nm = ev["t"].to_numpy(), ev["name"].to_numpy()
    m = np.where(np.isin(nm, SIG_MARKERS))[0]
    if len(m):
        m = m[np.r_[True, np.diff(t[m]) > SIG_SAME_BOOT_SECONDS]]
    if not len(m):
        return [], 0
    # only background (heartbeat-class) events: usage and state events (unlocks, app switches, screen on) also
    # happen at every ordinary wake-up, so they do not tell a boot apart
    item, keep = event_items(ev), (ev["cls"].to_numpy() == "heartbeat")
    count = {}
    for i in m:
        a, b = np.searchsorted(t, t[i] - BOOT_BURST_SECONDS, "left"), np.searchsorted(t, t[i] + BOOT_BURST_SECONDS, "right")
        for x in set(item[a:b][keep[a:b]]):
            count[x] = count.get(x, 0) + 1
    return sorted(x for x, c in count.items() if c >= SIG_CORE_SHARE * len(m)), len(m)


def pooled_core(cores):
    """Signature for devices with too few confirmed boots: the items in the signature of at least
    SIG_POOL_SHARE of the devices that have one (cores: one list of items per DEVICE)."""
    cores = [c for c in cores if c]
    count = {}
    for c in cores:
        for x in set(c):
            count[x] = count.get(x, 0) + 1
    return sorted(x for x, n in count.items() if n >= SIG_POOL_SHARE * len(cores))


def signature_scores(ev, k, core):
    """Share of the signature items present in the 60 s after each interval k (the phase a boot would produce)."""
    k = np.asarray(k)
    if not len(k) or not len(core):
        return np.full(len(k), np.nan)
    t, nm = ev["t"].to_numpy(), ev["name"].to_numpy()
    idx = {x: i for i, x in enumerate(core)}
    item = event_items(ev)
    cid = np.fromiter((idx.get(x, -1) for x in item), dtype=np.int64, count=len(item))
    cid[ev["cls"].to_numpy() != "heartbeat"] = -1
    ends = np.searchsorted(t, t[k + 1] + BOOT_BURST_SECONDS, "right")
    out = np.empty(len(k))
    for j, (a, b) in enumerate(zip(k + 1, ends)):
        c = cid[a:b]
        out[j] = len(np.unique(c[c >= 0])) / len(core)
    return out


def normal_unlock(ev, k):
    """True where the next unlock after interval k is an ordinary one: a Keyguard Hidden with no User Unlocked
    and no Device Startup up to BOOT_BURST_SECONDS after it. Android writes User Unlocked at the first unlock
    after every boot, so an ordinary unlock means no boot happened since the stretch began. Compared by time:
    at a boot, Keyguard Hidden / Shown, Screen Interactive and User Unlocked carry the same timestamp."""
    k = np.asarray(k)
    t, nm = ev["t"].to_numpy(), ev["name"].to_numpy()
    if not len(k):
        return np.zeros(0, dtype=bool)

    def next_time(name):
        i = np.where(nm == name)[0]
        if not len(i):
            return np.full(len(k), np.inf)
        j = np.searchsorted(i, k + 1, "left")
        return np.where(j < len(i), t[i[np.minimum(j, len(i) - 1)]], np.inf)
    kh = next_time("Keyguard Hidden")
    return np.isfinite(kh) & (next_time("User Unlocked") > kh + BOOT_BURST_SECONDS) \
        & (next_time("Device Startup") > kh + BOOT_BURST_SECONDS)


def interval_labels(ev, sig=None):
    """Labels of every interval between consecutive events (before merging): dict of arrays
    t (events), d (interval lengths), strict / likely (state bit masks), r_strict / r_likely (rule ids),
    and the Off-or-On evidence of each interval: off_sign / on_sign (rule ids, -1 if none), boot_score, conflict.
    sig: dict(core=[items], cut=float, kind="device"|"pooled") for the boot signature, or None."""
    t, nm, cls = ev["t"].to_numpy(), ev["name"].to_numpy(), ev["cls"].to_numpy()
    n = len(t)
    if n < 2:
        return None
    K = n - 1
    d = np.diff(t)

    # 1. screen evidence (both layers)
    base = np.full(K, IDLE | ACTIVE, dtype=np.int8)
    rule = np.full(K, _R["screen_unknown"], dtype=np.int8)
    # signs of use: usage events, except those of lock-screen feeds, which put themselves in front whenever the
    # display wakes and log Resumed/Paused/Stopped within a fraction of a second while the phone lies locked
    # (4111_P02: Metro Play, 13,324 resumes) -- these are a sign of a locked phone, not of use
    pkg_all = ev["app_package_name"].astype(str)
    usage_idx = np.where((cls == "usage") & ~pkg_all.str.contains(LOCKSCREEN_FEED_APP).to_numpy())[0]
    def lost_off(s, e):
        """Screen on from s, the screen-off not logged before e: Active up to the last usage event, then unsure,
        then Idle once only background events have been logged for SCREEN_TAIL_IDLE_SECONDS (4088_P01)."""
        j = np.searchsorted(usage_idx, e, "left") - 1
        lu = usage_idx[j] if j >= 0 and usage_idx[j] >= s else s
        base[s:lu], rule[s:lu] = ACTIVE, _R["screen_on_active"]
        base[lu:e], rule[lu:e] = IDLE | ACTIVE, _R["screen_on_tail"]
        late = np.arange(lu, e)[t[lu:e] - t[lu] >= SCREEN_TAIL_IDLE_SECONDS]
        base[late], rule[late] = IDLE, _R["screen_on_tail_idle"]
        # a silence of more than SCREEN_ON_MAX_SILENCE_SECONDS that starts at the last sign of use and ends with the
        # screen off: the use ended somewhere inside it and that moment was lost. No screen time can be granted for
        # it, so it is Idle (reviewer, 4090_P01: YouTube resumed at 00:31, next event a notification at 06:00)
        gone = np.arange(lu, e)[(base[lu:e] == (IDLE | ACTIVE)) & (d[lu:e] > SCREEN_ON_MAX_SILENCE_SECONDS)]
        base[gone], rule[gone] = IDLE, _R["screen_on_end_lost"]

    for s, e, state, end in screen_runs(nm):
        if state == "on":
            # a silence of LONG_QUIET_OFF_SECONDS or more breaks the run: the screen did not stay on across it.
            # Up to and including the silence the screen-off was lost; after it the screen state is unknown
            brk = s + np.where(d[s:e] >= LONG_QUIET_OFF_SECONDS)[0]
            if len(brk):
                lost_off(s, brk[0] + 1)
                base[brk[0] + 1:e], rule[brk[0] + 1:e] = IDLE | ACTIVE, _R["screen_unknown"]
            elif end == "off":
                base[s:e], rule[s:e] = ACTIVE, _R["screen_on"]
            else:
                lost_off(s, e)
        elif state == "off":
            if end == "off":
                base[s:e], rule[s:e] = IDLE | ACTIVE, _R["screen_off_lost_on"]
                # the screen-on was lost, but it cannot have come before the first sign of use: from the screen-off
                # up to the first usage event of the run the screen was still off (9124_P01)
                j = np.searchsorted(usage_idx, s, "right")
                # a Paused/Stopped is not a new sign of use: the screen-off itself causes one, and a pause with no
                # start (4111_P02) shows that events were lost but not when the screen came on. The logged
                # screen-off stands until something starts: a Resumed, an interaction, a notification seen, an unlock
                while j < len(usage_idx) and usage_idx[j] < e \
                        and nm[usage_idx[j]] in ("Activity Paused", "Activity Stopped"):
                    j += 1
                fu = usage_idx[j] if j < len(usage_idx) and usage_idx[j] < e else e
                base[s:fu], rule[s:fu] = IDLE, _R["screen_off_until_use"]
            else:
                base[s:e], rule[s:e] = IDLE, _R["screen_off"]

    # where the screen state is unsure because a screen-on was lost or the state is unknown: Idle once only background
    # events have been logged for SCREEN_TAIL_IDLE_SECONDS since the last usage event (4103_C01: 24 h of notifications
    # after the last sign of use). Only turns unsure into Idle, never touches Active.
    if len(usage_idx):
        idx = np.arange(K)
        j = np.searchsorted(usage_idx, idx, "right") - 1
        quiet_use = (j >= 0) & (t[idx] - t[usage_idx[np.maximum(j, 0)]] >= SCREEN_TAIL_IDLE_SECONDS)
        bg = quiet_use & (base == (IDLE | ACTIVE)) & np.isin(rule, [_R["screen_off_lost_on"], _R["screen_unknown"]])
        base[bg], rule[bg] = IDLE, _R["background_only"]

    long_on = (base == ACTIVE) & (d > SCREEN_ON_MAX_SILENCE_SECONDS)
    # ... unless the same user app is Resumed before the silence and Paused after it: it stayed in front, so the
    # screen stayed on (a pause is logged when the screen goes off). Counted as screen time whether or not anyone
    # was watching, which the log cannot tell (reviewer, 4090_P01: YouTube resumed 03:13, paused 07:04)
    li = np.where(long_on)[0]
    front = li[app_continuity(ev, li, "in_front")]
    long_on[front] = False
    rule[front] = _R["screen_on_same_app"]
    base[long_on], rule[long_on] = IDLE | ACTIVE, _R["screen_on_long_silence"]

    # 2. Off or On? (step 1) -- decided by the events around each quiet stretch of at least the tolerance
    cand = np.where(d >= TOLERANCE_SECONDS)[0]
    strict = base.copy()
    strict[cand] |= OFF                      # strict: a reboot may hide in it unless an On sign says otherwise
    likely = base.copy()                     # likely: not Off unless an Off sign says so
    r_strict, r_likely = rule.copy(), rule.copy()
    off_sign = np.full(K, -1, dtype=np.int8)
    on_sign = np.full(K, -1, dtype=np.int8)
    boot_score = np.full(K, np.nan)
    conflict = np.zeros(K, dtype=bool)

    # On signs: an ordinary unlock afterwards, or the same user app on both sides
    nu = normal_unlock(ev, cand)
    co = app_continuity(ev, cand)
    on_sign[cand[co]] = _R["app_continuity"]
    on_sign[cand[nu]] = _R["normal_unlock"]          # the stronger of the two when both hold
    has_on = on_sign >= 0
    strict[has_on] &= ~OFF
    r_strict[has_on] = on_sign[has_on]

    # Off signs: the dark stretch next to a shutdown or a boot sign
    def boot_gap(jb):
        lo = max(int(np.searchsorted(t, t[jb] - BOOT_BURST_SECONDS, "left")) - 1, 0)
        return None if jb <= lo else lo + int(np.argmax(d[lo:jb]))

    stops = np.where((cls == "usage") | np.isin(nm, ["Device Startup", "User Unlocked", "Device Shutdown"]))[0]
    # an unclean shutdown (forced restart: stamped at the last save, closes nothing) leaves its dark stretch only
    # likely Off: the use between the save and the real power-off is lost (Samsung test phone, 2026-10-08)
    kinds = dict(shutdown_kinds(ev))
    for i in np.where(nm == "Device Shutdown")[0]:
        j = np.searchsorted(stops, i, "right")
        jend = stops[j] if j < len(stops) else n - 1
        if jend > i:
            k = i + int(np.argmax(d[i:jend]))
            if off_sign[k] < 0 or kinds.get(int(i)) == "clean":   # duplicate rows: a clean one wins
                off_sign[k] = _R["shutdown_before"] if kinds.get(int(i)) == "clean" else _R["shutdown_unclean_before"]
    for jb in np.where(nm == "Device Startup")[0]:
        k = boot_gap(jb)
        if k is not None:
            off_sign[k] = _R["shutdown_startup"] if off_sign[k] == _R["shutdown_before"] else \
                _R["shutdown_unclean_startup"] if off_sign[k] in (_R["shutdown_unclean_before"], _R["shutdown_unclean_startup"]) else _R["startup_after"]
    for jb in np.where(nm == "User Unlocked")[0]:
        k = boot_gap(jb)
        if k is not None and off_sign[k] == _R["shutdown_unclean_before"]:
            off_sign[k] = _R["shutdown_unclean_startup"]
        elif k is not None and off_sign[k] < 0 and d[k] >= TOLERANCE_SECONDS:
            off_sign[k] = _R["unlocked_after"]
    if sig and sig.get("core"):                       # the boot signature of this device (or the pooled one)
        sc = signature_scores(ev, cand, sig["core"])
        boot_score[cand] = sc
        hit = cand[sc >= sig["cut"]]
        hit = hit[off_sign[hit] < 0]
        off_sign[hit] = _R["boot_signature"]
    # "a system app paused without having started" is no longer used as an Off sign (reviewer, 2026-10-02): too weak.
    # In A1 it contradicted a normal unlock in 903 stretches and stood alone in only 44; a phone waking from sleep
    # produces the same pattern. The rule id stays in RULES so that ids in older outputs keep their meaning.

    conf = np.isin(off_sign, [_R[r] for r in CONFIRMED_OFF])
    sigoff = off_sign == _R["boot_signature"]
    weak = off_sign == _R["system_pausefirst_after"]
    # logged boot events settle it in both layers, whatever else is around
    strict[conf], likely[conf] = OFF, OFF
    r_strict[conf], r_likely[conf] = off_sign[conf], off_sign[conf]
    # the boot signature is a strong sign: Off in the likely layer even against an On sign (the boot's own
    # markers were lost); in the strict layer the stretch is possibly Off again
    likely[sigoff], r_likely[sigoff] = OFF, off_sign[sigoff]
    strict[sigoff] |= OFF
    r_strict[sigoff] = rule[sigoff]
    # an unlock (Keyguard Hidden) right after a boot storm is the person unlocking the freshly booted device, not a
    # sign that it stayed on (7261_C01): drop the On sign, no conflict
    on_sign[sigoff] = -1
    has_on = on_sign >= 0
    # an unclean shutdown: Off in the likely layer even against an On sign (the boot follows); in the strict layer
    # possibly Off, since the phone was on with its events lost for an unknown part of the stretch
    unc = np.isin(off_sign, [_R[r] for r in UNCLEAN_OFF])
    likely[unc], r_likely[unc] = OFF, off_sign[unc]
    strict[unc] |= OFF
    r_strict[unc] = rule[unc]
    on_sign[unc] = -1
    has_on = on_sign >= 0
    # a system app pausing first is a weak sign: Off in the likely layer only when no On sign contradicts it
    w_ok = weak & ~has_on
    likely[w_ok], r_likely[w_ok] = OFF, off_sign[w_ok]
    strict[w_ok] |= OFF
    conflict |= weak & has_on
    # a quiet stretch of 6 h or more is Off in the likely layer, whatever On sign it has: a phone that is on does
    # not stay silent that long, and "no boot marker afterwards" proves nothing when the log itself stopped
    # (4520_P01: the log stops in the middle of a boot and resumes 139 days later like a running phone)
    lq = (d >= LONG_QUIET_OFF_SECONDS) & ~conf & ~sigoff & ~unc
    # (reviewer, 2026-10-08) boots almost always log a marker (A1: Startup / User Unlocked at 2,110 boots; boots without
    # any marker are rare), so a long silence with no power marker is not a power-off: the log was lost ("No logging",
    # both layers). From NO_LOGGING_OFF_SECONDS on it is taken as Off in the likely layer, as before.
    nolog = lq & (d < NO_LOGGING_OFF_SECONDS)
    lq = lq & ~nolog
    strict[nolog], likely[nolog] = NOLOG, NOLOG
    r_strict[nolog], r_likely[nolog] = _R["no_logging"], _R["no_logging"]
    off_sign[nolog] = _R["no_logging"]
    conflict[nolog] = False
    # 2 days or more with no power marker: "No logging, likely off" in the likely layer, "No logging" in the strict
    # layer (reviewer, 2026-10-08: the log was lost; in reality such long silences are the phone powered off)
    off_sign[lq] = _R["long_quiet"]
    likely[lq], r_likely[lq] = NOLOG_OFF, _R["long_quiet"]
    strict[lq], r_strict[lq] = NOLOG, _R["long_quiet"]
    conflict[lq] = False
    return dict(t=t, d=d, strict=strict, likely=likely, r_strict=r_strict, r_likely=r_likely,
                off_sign=off_sign, on_sign=on_sign, boot_score=boot_score, conflict=conflict, screen=base)


def quiet_stretches(ev, x=None):
    """The quiet stretches (gaps between two consecutive events, no event inside, at least TOLERANCE_SECONDS)
    that a person should look at, with the evidence of step 1. reason:
      unsure            the state is not settled in at least one layer
      conflict          an Off sign and an On sign on the same stretch
      continuity_check  settled only by continuity and longer than CONTINUITY_REVIEW_SECONDS
      app_usage         (separate list, not a review reason) counted as Active because the same user app is
                        resumed before the silence and paused after it; column app names it
      long_off_check    Off by the long-silence rule while the screen was not logged off before it (could hide screen time)
      no_logging        No logging / No logging, likely off: a silence of 6 h or more with no power marker"""
    x = interval_labels(ev) if x is None else x
    if x is None:
        return pd.DataFrame()
    t, d = x["t"], x["d"]
    conf = [OFF, IDLE, ACTIVE, NOLOG, NOLOG_OFF]
    big = d >= TOLERANCE_SECONDS
    unsure = big & (~np.isin(x["strict"], conf) | ~np.isin(x["likely"], conf))
    by_on = big & (x["on_sign"] >= 0) & ~np.isin(x["likely"], [OFF, NOLOG, NOLOG_OFF])
    cont_check = by_on & (x["on_sign"] == _R["app_continuity"]) & (d > CONTINUITY_REVIEW_SECONDS)
    # Off by the long-silence rule, but the screen was not logged off when the silence began: it could hide screen time
    long_off = big & (x["off_sign"] == _R["long_quiet"]) & (x["screen"] != IDLE) & (d < LONG_QUIET_SURE_SECONDS)
    # not a review reason, a separate list: silences counted as app use because the same app is in front on both sides
    app_use = big & (x["r_likely"] == _R["screen_on_same_app"]) & (x["likely"] == ACTIVE)
    # (reviewer, 2026-10-08) No-logging silences go on the review list too: settled by rule, but to be looked at
    nolog = big & (np.isin(x["strict"], [NOLOG, NOLOG_OFF]) | np.isin(x["likely"], [NOLOG, NOLOG_OFF]))
    reason = np.select([x["conflict"], long_off, nolog, unsure, cont_check, app_use],
                       ["conflict", "long_off_check", "no_logging", "unsure", "continuity_check", "app_usage"], "")
    k = np.where(big & (reason != ""))[0]
    nm, pkg = ev["name"].to_numpy(), ev["app_package_name"].astype(str).to_numpy()
    res = np.where(nm == "Activity Resumed")[0]                       # the app in front when the silence began
    j = np.searchsorted(res, k, "right") - 1
    front = np.where(j >= 0, pkg[res[np.maximum(j, 0)]], "") if len(res) else np.full(len(k), "")
    lab = np.vectorize(LABELS.get, otypes=[object])
    rn = np.array(RULES + [""], dtype=object)          # index -1 -> ""
    return pd.DataFrame(dict(
        stretch_no=k + 1, start=t[k], end=t[k + 1], duration_s=d[k], reason=reason[k],
        strict=lab(x["strict"][k]) if len(k) else [], likely=lab(x["likely"][k]) if len(k) else [],
        rule_strict=rn[x["r_strict"][k]], rule_likely=rn[x["r_likely"][k]],
        off_sign=rn[x["off_sign"][k]], on_sign=rn[x["on_sign"][k]], boot_score=np.round(x["boot_score"][k], 3),
        left_event=nm[k], left_app=pkg[k], right_event=nm[k + 1], right_app=pkg[k + 1],
        app=np.where(reason[k] == "app_usage", front, "")))


def stretch_signs(ev, x):
    """Step-1 summary of EVERY quiet stretch of at least the tolerance: verdict (Off / On / Unsure / Conflict) and
    the sign that decided it. For the statistics; one row per stretch."""
    d = x["d"]
    k = np.where(d >= TOLERANCE_SECONDS)[0]
    rn = np.array(RULES + [""], dtype=object)
    off, on = x["off_sign"][k], x["on_sign"][k]
    is_off = np.isin(x["likely"][k], [OFF, NOLOG_OFF])
    nolog = x["likely"][k] == NOLOG
    verdict = np.where(x["conflict"][k], "Conflict", np.where(is_off, "Off", np.where(nolog, "No logging", np.where(on >= 0, "On", "Unsure"))))
    how = np.where(x["conflict"][k], np.char.add(np.char.add(rn[off].astype(str), " vs "), rn[on].astype(str)),
                   np.where(is_off | nolog, rn[off], rn[on]))
    return pd.DataFrame(dict(duration_s=d[k], verdict=verdict, how=how))


def compute(ev, x=None, sig=None):
    """Interval table of device states for one log (events from load_events, sorted by time).
    Consecutive intervals with the same labels and rules are merged into one row."""
    x = interval_labels(ev, sig) if x is None else x
    if x is None:
        return pd.DataFrame()
    t, d, strict, likely, r_strict, r_likely = (x[k] for k in ("t", "d", "strict", "likely", "r_strict", "r_likely"))
    K = len(d)
    chg = np.r_[True, (strict[1:] != strict[:-1]) | (likely[1:] != likely[:-1])
                | (r_strict[1:] != r_strict[:-1]) | (r_likely[1:] != r_likely[:-1])]
    st = np.where(chg)[0]
    en = np.r_[st[1:], K]
    lab = np.vectorize(LABELS.get)
    rn = np.array(RULES, dtype=object)
    return pd.DataFrame(dict(
        start=t[st], end=t[en], duration_s=t[en] - t[st],
        strict=lab(strict[st]), likely=lab(likely[st]),
        rule_strict=rn[r_strict[st]], rule_likely=rn[r_likely[st]],
        n_events=en - st + 1, longest_silence_s=np.maximum.reduceat(d, st)))


def summarize(states):
    """Hours per label in each layer."""
    out = {}
    for layer in ("strict", "likely"):
        h = states.groupby(layer)["duration_s"].sum() / 3600
        out[layer] = h.reindex(LABEL_ORDER).fillna(0.0)
    return pd.DataFrame(out)


def main(argv=None):
    import argparse
    import os
    ap = argparse.ArgumentParser(description="Device states for one reordered log")
    ap.add_argument("reordered_csv")
    ap.add_argument("out_dir")
    a = ap.parse_args(argv)
    os.makedirs(a.out_dir, exist_ok=True)
    s = compute(load_events(a.reordered_csv))
    stem = os.path.basename(a.reordered_csv)[:-4]
    s.to_csv(os.path.join(a.out_dir, stem + "_STATES.csv"), index=False)
    print(summarize(s).round(1).to_string())


if __name__ == "__main__":
    main()
