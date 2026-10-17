# Representative scenarios

Started 2026-10-09 (David: "we also need a list of representative scenarios").
Each scenario is one real case, kept with its full event trace, so that it can be shown in the paper, used to check a rule, or used as a test case for the feature table / model. The pattern book (claude/pattern-book.md) holds the general patterns; scenarios are concrete instances of them.

Each entry: the problem it illustrates, where to find it (file, layer, stretch), the event trace around it, the reading, how sure we are, the patterns it shows, the current label and what we think it should be, and its **scenario label** (below).
Times as logged (UTC) unless the entry says otherwise. The review page shows the same stretch in local time.
Review page: the toolbox's local review app (`make review`), tab **Scenarios**, one scenario at a time with a comment box. Its copy of this list is eyes-toolbox `docs/scenarios.md`.

## Scenario label (David, 10-10: "for each representative scenario, we need to label it")
For each level, what is missing from the log. David's example (S1): "for App, the YouTube resume is lost; for device status, the screen-interactive is lost".
- **Levels (David, 10-10):** three levels of events.
  - **Power:** Device Shutdown, Device Startup, User Unlocked (power cycles, clean / unclean).
  - **Device state:** Screen Interactive / Non-interactive, Keyguard Shown / Hidden (screen on / off, locked / unlocked).
  - **App:** Activity Resumed / Paused / Stopped and Foreground Service Start / Stop. Sub-tracks: **app in front** (main), **small window** (Paused with no Stopped), and two special sub-tracks (David, 10-10): **car projection** and **foreground service** (audio, calls, navigation).
  - Small window and foreground service are independent (phone tests 10-03 / 10-07): a YouTube Short has a small window with no service; YouTube audio-only (top-left bar) has a service with no small window; a normal YouTube video has both; Chrome web video has a service and no small window.
  - Quiet stretches are not a level: they are gaps between events, across all levels.
- **Per level / sub-track, one of:**
  - **complete**: the events that bound the state are logged;
  - **lost: <event>**: the event must have happened (later events prove it) but is not in the log;
  - **not emitted: <event>**: Android never writes it in this situation (e.g. a clean shutdown does not Stop a small window); not a loss;
  - **wrong time: <event>**: logged, but its time is not when it happened (e.g. an unclean shutdown stamped at the last save);
  - **not logged: <field>** (added 10-15, S6): every event is there, but Chronicle drops a field Android writes (the activity class name), and without it the events can be read two ways;
  - **Truth** (added 10-16, S7, David): the log is complete and the event order alone gives the true reading, though a strict package-only chain would call it broken. A scenario labelled Truth records a correct Android behaviour that a rule must accept, not a defect;
  - **none**: nothing in this level is involved.
- A level is marked **lost** only when the evidence shows the event happened in or near the scenario. If it may have happened long before (e.g. a boot some time before the log began), the level is **none** (David, 10-10: S1 power is "simply NONE, not bootup missing").
- **Cause of the loss:** log start (the file begins mid-state), log end, logger gap, unclean shutdown, logger design (S6), unknown.
- **Edge:** start lost, end lost, both, or inside.
- **Inferred state** and **confidence** (certain / high probability / unknown).

---

## S1. Watching YouTube through a silence (log starts mid-video)
- **Problem it illustrates:** a log that starts in the middle of use. The YouTube Resumed and the Screen Interactive happened before the file began, so pairing events finds no YouTube use at all, and the 8-minute silence looks like the device sitting idle. Only the evidence after the silence settles it, with high probability: rotation events, a YouTube Paused with no Resumed, and a screen-off minutes later. Defect: **lost** at the start edge.
- **Where:** 4666_C01 (child, tablet), folder A1_Cohort_D, strict layer, quiet stretch #8. Device state review → File by file → 4666_C01.
- **Silence:** 2025-04-24 21:48:10.303 → 21:56:34.423 (8 min 24 s).
- **Event trace:**

| Time | Event | App |
|---|---|---|
| 21:47:03.661 | Configuration Change (first event of the file) | android |
| 21:47:08 – 21:48:10 | 7 more Configuration Change | android |
| **21:48:10 – 21:56:34** | **silence (8 min 24 s)** | |
| 21:56:34.423 – 21:56:42.788 | 6 Configuration Change | android |
| 21:56:44.525 | Activity Resumed | home screen (launcher3) |
| 21:56:45.157 | **Activity Paused**, no Resumed anywhere before | **YouTube** |
| 21:56:45.562 | Activity Stopped | YouTube |
| 21:56:48 – 22:00:47 | Play Store, Gmail, permission screen, Chronicle app, Settings (setting up the study app) | |
| 22:04:59.169 | Screen Non-interactive | android |

- **Reading (David, 10-08):** (1) a series of Configuration Change events; (2) YouTube Paused / Stopped immediately after; (3) Screen Non-interactive comes later; (4) other apps Resumed / Paused close after. So the device was Active through the silence (app activity right after it, before the screen-off), and very likely watching YouTube (rotation to and from full screen; YouTube is the app that leaves the front).
- **Confidence:** high probability, not certain: there is no YouTube Resumed, because the log starts during the video (David: "we can't say it 100%... but we have very high confidence").
- **Patterns:** B3 (video in front through the silence), B4 (app Paused at the end of a silence, never Resumed), B5 (configuration changes = rotation).
- **Current label:** strict and likely Unsure IA (Active or Idle). **Should be:** Active, YouTube (likely).
- **Features (stretch_features.csv.gz):** before_config_n 6, after_config_n 6, before_screen unknown, after_boot False, after_rp_event Activity Resumed (home screen, 10.1 s), after_burst_unpaired_user_pause True (YouTube), after_screen off after 504.7 s.
- **Note:** the whole file is 42 minutes (the evening the study app was installed); not a normal day of use.
- **Scenario label** (David, 10-10):

| Level | Status |
|---|---|
| Power | **none** (no sign of a boot near the file's start; the tablet was already on) |
| Device state | **lost: Screen Interactive** (the screen was on: apps run and a screen-off follows at 22:04:59) |
| App: in front | **lost: YouTube Activity Resumed** |
| App: small window, car projection, foreground service | none |

  Cause: log start (the file begins mid-video). Edge: start lost. Inferred: Active, YouTube. Confidence: high probability.

---

## S2. Logger stops mid-use and comes back a year later
- **Problem it illustrates:** telling "the device was off" from "the logger was not recording". The phone was in use on both sides of a 352-day silence, and there is no shutdown or boot at either edge, so the gap is missing log, not an off device. What the phone did during the gap cannot be known. Open question: whether such stretches belong to the observation window at all. Defect: **lost** at both edges (logger gap).
- **Where:** 4090_C01 (child, phone), folder A12_Cohort_B. Longest silence of the file.
- **Silence:** 2024-10-15 11:03:07 → 2025-10-02 15:38:51 (352 days).
- **Event trace:** before: mini-game Stopped 11:03:07, Chrome Paused 11:03:07, notes app Resumed 11:03:07 (never Paused, no screen-off, no shutdown). After: Messages service start / stop 15:38:51, dialer service and notifications 15:42:17-15:42:20, **Roblox Paused 15:42:19 with no Resumed**, dialer Resumed, Roblox Stopped. No boot on either side.
- **Reading:** the phone was in use when logging stopped and in use (Roblox open) when it came back: the logger was not recording. Over 352 days the phone was surely also off at times, but when cannot be seen. The file holds 11 days of real data (4-15 Oct 2024) and one last day.
- **Confidence:** certain that the log is missing; what the phone did in between is unknown.
- **Patterns:** B1 (No logging), B2 (logger stops and restarts mid-use).
- **Current label:** strict No logging, likely No logging, likely off. David (10-08): apparently device off. Open: treat as outside the observation window.
- **Scenario label** (proposed):

| Level | Status |
|---|---|
| Power | unknown: any shutdowns / boots in 352 days not logged |
| Device state | lost: Screen Non-interactive (start edge) and Screen Interactive (end edge), and everything between |
| App: in front | lost: notes app Paused (start edge); lost: Roblox Resumed (end edge) |
| App: small window, car projection, foreground service | unknown |

  Cause: logger gap. Edge: both. Inferred: No logging, likely off. Confidence: certain that the log is missing; state unknown.

---

## S3. Clean power-off from the home screen (test phone)
- **Problem it illustrates:** the baseline: what a complete power cycle looks like, with ground truth. It also shows that a missing event is not always a lost one. A clean shutdown writes no Screen Non-interactive, because the shutdown itself is the screen-off. Reading that absence as a loss would be wrong. Defect: none (**not emitted** only).
- **Where:** Samsung test phone, 2026-10-08, run 2 (raw dump samsung01_usagestats_dump_2026-10-08_0822_run2b.txt).
- **Event trace:** 08:13:12 screen on, home; 08:17:57 YouTube; 08:18:16 home; 08:18:18 Chrome; 08:18:22 home; **08:18:41 home screen Paused + Stopped + Device Shutdown, same second**; 08:19:36 Screen Interactive + User Unlocked + Device Startup, same second; 08:19:37 Settings Paused + Stopped (no Resumed), home Resumed; boot services.
- **Ground truth:** David turned the phone off from the power menu and on again within about a minute.
- **Patterns:** A2 (clean shutdown), A1 (boot).
- **Label:** Off, confirmed (08:18:41 → 08:19:36).
- **Scenario label:**

| Level | Status |
|---|---|
| Power | complete |
| Device state | not emitted: Screen Non-interactive at the shutdown (the shutdown is the screen-off) |
| App: in front | complete |
| App: small window, car projection, foreground service | none |

  Cause: none. Inferred: Off. Confidence: certain (ground truth).

---

## S4. Forced restart erases the last minutes (test phone)
- **Problem it illustrates:** an unclean shutdown both loses events and stamps the shutdown at the wrong time. Android writes Device Shutdown at its last save, so 11.7 minutes of real use vanish, and a phone that was off for seconds looks off for 12 minutes. A naive reading counts the device as off and its use as zero. Defects: **wrong time** (Device Shutdown) and **lost** (the minutes before the power-off).
- **Where:** Samsung test phone, 2026-10-08, run 3 (dumps _0822_run2b.txt before, _0833_forced.txt after).
- **Event trace:** before the forced restart the log held 15 events 08:19:42-08:20:22 (boot services, notifications). After it: **Device Shutdown at 08:19:41** (4 s after the previous boot), those 15 events gone, nothing until the next boot 08:31:24 (screen on + User Unlocked + Device Startup).
- **Ground truth:** David held side key + volume down until the phone restarted, about 08:31; he had used the phone (button presses, power menus) 08:22-08:29.
- **Reading:** the shutdown is stamped at Android's last save, not at the power-off; 11.7 min are lost, of which the phone was off only seconds.
- **Patterns:** A3 (unclean shutdown), A1 (boot).
- **Label:** Off, likely; start unknown.
- **Scenario label:**

| Level | Status |
|---|---|
| Power | wrong time: Device Shutdown (08:19:41 = last save; real power-off about 08:31) |
| Device state | lost: screen on / off 08:22-08:29 |
| App: in front | lost: home screen Paused / Stopped; lost: the 15 events 08:19:42-08:20:22 |
| App: foreground service | lost: Samsung Messages service Stop |
| App: small window, car projection | none |

  Cause: unclean shutdown. Edge: end lost (before the power-off). Inferred: on (use lost), then off for seconds. Confidence: certain (ground truth).

---

## S5. Small window and service left open by a clean power-off (test phone)
- **Problem it illustrates:** the side tracks (a small window and a foreground service) have no closing event at a clean shutdown. Android closes only the app in front. Pairing events would leave YouTube's small window and its audio service running past the power-off, possibly for days. The rule is that they end at the shutdown. Defect: **not emitted** on the small-window and service tracks.
- **Where:** Samsung test phone, 2026-10-08, run 4 (dump _0915_pip_shutdowns.txt).
- **Event trace:** 09:10:10 YouTube; 09:10:17 play + YouTube service start; 09:10:25 YouTube Paused, no Stopped (small window), home Resumed; **09:10:51 home Paused + Stopped + Device Shutdown**; YouTube never Stopped, its service never Stopped; 09:11:45 boot.
- **Ground truth:** David put a playing YouTube video into a small window, then powered off from the menu.
- **Reading:** a clean shutdown closes only the app in front; the small window and the service end at the shutdown without a closing event.
- **Patterns:** A2, C1 (small window), E1 (services at a shutdown).
- **Label:** Off, confirmed; small window and service periods end at 09:10:51.
- **Scenario label:**

| Level | Status |
|---|---|
| Power | complete |
| Device state | not emitted: Screen Non-interactive at the shutdown |
| App: in front | complete (home screen) |
| App: small window | not emitted: YouTube Stopped (ends at the shutdown) |
| App: foreground service | not emitted: YouTube service Stop (ends at the shutdown) |
| App: car projection | none |

  Cause: none. Inferred: small window and service until 09:10:51, then Off. Confidence: certain (ground truth).

---

## S6. A 48-minute game lost to a missing class name (EyesApp, Aizhong's phone)
- **Problem it illustrates:** a log can be complete and still mislead, because Chronicle keeps only the package and drops the activity class. When a game's splash screen hands over to the game screen, the splash screen's Stopped arrives 2 s later. Without class names it looks like the game itself was stopped, so the toolbox read "app killed" and counted 0.1 min of a session Android counted at 72 min. The fix is a heuristic; logging the class name removes the guess. Defect: **not logged** (a new kind, beside lost, not emitted and wrong time).
- **Why it is here (David, 10-15):** "if Aizhong's phone has no activity log/event missing, then the toolbox should always work correctly", and this case shows that **not logging the class name is a flaw** of Chronicle. Every event was logged, yet the package-only log could be read two ways, and the toolbox read it the wrong way.
- **Where:** Aizhong Mate30Pro (Huawei, HarmonyOS / Android 12, EyesApp), 2026-10-11, Asia/Shanghai. Delta Force (com.tencent.tmgp.dfm), an Unreal Engine game. Server: device page → Screen Time, 10-11.
- **Event trace (local time; class names as EyesApp logs them, Chronicle would keep only the package):**

| Time | Event | Package | Class (not in Chronicle) |
|---|---|---|---|
| 12:55:14.360 | Activity Resumed | home screen | UniHomeLauncher |
| 12:55:14.490 | Keyguard Hidden | android | |
| 12:55:17.295 | Activity Paused | home screen | UniHomeLauncher |
| 12:55:17.320 | Activity Resumed | Delta Force | **SplashActivity** |
| 12:55:17.464 | Activity Paused | Delta Force | **SplashActivity** |
| 12:55:17.467 | Activity Resumed | Delta Force | **GameActivity** |
| 12:55:19.559 | Activity Stopped | Delta Force | **SplashActivity** (2.09 s after GameActivity's Resumed) |
| 12:55:19.591 | Activity Stopped | home screen | UniHomeLauncher |
| **12:55:19 – 13:42:59** | **no events (game being played)** | | |
| 13:42:59.565 | Activity Paused | Delta Force | GameActivity |
| 13:42:59.566 | Activity Resumed | home screen | UniHomeLauncher |
| 13:42:59.911 | Activity Stopped | Delta Force | GameActivity |

- **Reading:** with class names it is certain. The Stopped at 12:55:19 is the splash screen going invisible after the game screen came up (the game is slow to draw its first frame). GameActivity stayed in front until 13:42:59: **47 min 42 s of play**. The same pattern happened again at 14:02:10 → 14:18:01 (15 min 51 s).
- **The two readings of the package-only log:**
  1. Delta Force Stopped while in front, with no Paused, means **the app was killed at 12:55:19**. The later Paused has no Resumed (MissingActivityResumed).
  2. **The screen the app left** was Stopped. The game kept running until its Paused at 13:42:59.
  Without the class name, both fit the events. The toolbox chose (1), because the Stopped came more than its 2 s proximity window after the Resumed.
- **Ground truth:** Android's own daily total (DailyStats, from EyesApp) for Delta Force on 10-11 is 72.2 min. Pairing the events by class name gives the same. The toolbox gave 0.1 min.
- **Fix (toolbox f10943c, pattern C7 in claude/pattern-book-addendum-1015.md):** while the screen is on, a Stopped within 10 s of a Resumed goes to the activity Paused at the hand-over, if it has no Stopped yet. With the fix the toolbox matches. Across 50 device-days, mean error fell from 10.1 to 4.7 min/day against DailyStats. In A1, 19,037 "app killed" breaks are no longer made. **The fix is a heuristic (a time window plus the screen state). With class names, no guess is needed.**
- **Patterns:** C7 (late Stopped after an activity hand-over).
- **Scenario label:**

| Level | Status |
|---|---|
| Power | none |
| Device state | complete (Keyguard Hidden 12:55:14; screen on throughout) |
| App: in front | **not logged: activity class name**. All events are present; without the class, Stopped(SplashActivity) reads as Stopped(GameActivity) |
| App: small window, car projection, foreground service | none |

  Cause: logger design (Chronicle keeps the package, drops the class). Edge: inside. Inferred: Delta Force in front 12:55:17 → 13:42:59. Confidence: certain (class names, and Android's own daily total).
- **For the paper:** a fourth kind of log defect besides lost, not emitted and wrong time: the information was emitted by Android but **not logged** by the logger. Other cases of the same kind: one app's screens looking like a skipped Paused (C6, Facebook), and car screens (GhostActivity) mixed with phone use in Android Auto (E6).

---

## S7. Three screens of one app, logged as R P R P R S S P S (EyesApp, LiSiYu's RedMi) — Truth
- **Label: Truth** (David, 10-16). Nothing is lost and nothing is wrong. This is how Android logs an app moving through its own screens, and the reading below is the true one.
- **Problem it illustrates:** a correct log that a strict package-only chain would call broken. Chronicle drops the class name, so an app passing through three of its own screens shows, for one package: Resumed → Paused → Resumed → Paused → Resumed → Stopped → Stopped → Paused → Stopped. The two Stopped belong to the first two screens. They arrive while the third screen of the same app is in front, and that screen's own Paused comes later. A chain that takes "Stopped of the app in front, no Paused" as a failure stops there. In the chain method (claude/chain-method-1015.md) that put the boundary of an EventLost block at the wrong place (4103_C01, below).
- **Where:** LiSiYu RedMi (Xiaomi 2510DRK44C, Android 16, EyesApp 1.9; device 0c4878d3), 2026-10-07, Asia/Shanghai. WeChat (com.tencent.mm).
- **Event trace (local time; class names as EyesApp logs them, Chronicle would keep only the package):**

| Time | Event | Package | Class (not in Chronicle) |
|---|---|---|---|
| 17:02:04.784 | Activity Resumed | WeChat | **SoSoProxyUI** (screen 1) |
| 17:02:07.437 | Activity Paused | WeChat | SoSoProxyUI |
| 17:02:07.440 | Activity Resumed | WeChat | **RedirectUI** (screen 2) |
| 17:02:07.450 | Activity Paused | WeChat | RedirectUI |
| 17:02:07.452 | Activity Resumed | WeChat | **LauncherUI** (screen 3) |
| 17:02:07.505 | Activity Stopped | WeChat | SoSoProxyUI (screen 1) |
| 17:02:07.511 | Activity Stopped | WeChat | RedirectUI (screen 2) |
| 17:02:07 – 17:03:06 | WeChat main screen in use | | |
| 17:03:06.121 | Activity Paused | WeChat | LauncherUI (screen 3) |
| 17:03:06.124 | Activity Resumed | home screen | Launcher |
| 17:03:07.244 | Activity Stopped | WeChat | LauncherUI |

- **Reading:** three triplets, all complete: SoSoProxyUI 17:02:04.784 → 07.437 → 07.505; RedirectUI 07.440 → 07.450 → 07.511; LauncherUI 07.452 → 17:03:06.121 → 17:03:07.244. WeChat was in front from 17:02:04.784 to 17:03:06.121.
- **How common (EyesApp, all days to 10-16):**
  - The exact sequence R P R P R S S P S for one package occurs **93 times** on 8 devices: Alipay 57 (SchemeStartActivity → LiteProcessActivity → XRiverActivity, a mini-program opening), WeChat 23, others once each (Douyin, Kuaishou, Baidu, Fanqie reader, Brawl Stars, Messages).
  - The general form, a Stopped of an earlier screen while another screen of the same app is in front: **14,260 of 34,284 Stopped (42%)**, on 12 devices. Chrome (b566b43f, 10-08): ChromeTabbedActivity ↔ DownloadActivity, and ChromeLauncherActivity → ChromeTabbedActivity / CustomTabActivity, 12 times.
- **The same pattern in Chronicle (A1):** 4103_C01 (child, tablet), Power Cycle #5 (Bootup 2024-11-13 21:26:20.908), Chrome, America/New_York:

| Time | Event | Chrome screen |
|---|---|---|
| 21:29:06.720 | Activity Resumed | 1 |
| 21:29:10.281 | Activity Paused | 1 |
| 21:29:10.367 | Activity Resumed | 2 |
| 21:29:10.734 | Activity Paused | 2 |
| 21:29:10.769 | Activity Resumed | 3 |
| 21:29:13.249 | Activity Stopped | 1 |
| 21:29:13.367 | Activity Stopped | 2 |
| 21:29:15.802 | Activity Paused | 3 (YouTube Resumed at 21:29:15.920) |
| 21:29:17.792 | Activity Stopped | 3 |

  The backward chain construction failed at 21:29:13.249 and started the ScreenOn there, putting the minutes before it into EventLost. With the rule below it continues back to 21:28:54.613, where a real failure stops it (Play Store Resumed with no Paused).
- **Rule (David, 10-16: "we need a bit flexibility when constructing triplets"; toolbox 28f265f):** a Stopped of an app goes to an earlier Paused-not-Stopped screen of that app, also while a newer screen of the same app is in front, as long as that newer screen's own Paused comes later. Order only, no time window. A real kill (C8) differs: the app in front is Stopped with no Paused, and its screen never Pauses afterward.
- **Patterns:** C7 (late Stopped after an activity hand-over), C6 (one app's screens), proposed C9 (this one).
- **Scenario label:**

| Level | Status |
|---|---|
| Power | none |
| Device state | complete |
| App: in front | complete (**Truth**); in Chronicle, not logged: activity class name, but the order of events alone gives this reading |
| App: small window, car projection, foreground service | none |

  Cause: none (Android's normal order for screens of one app). Edge: inside. Inferred: WeChat in front 17:02:04.784 → 17:03:06.121. Confidence: certain (class names).
