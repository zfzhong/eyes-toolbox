"""
Event names and event classes (see the manual, "Event Classes").

Chronicle writes each Android usage event either by name ("Activity Stopped") or,
for events it has no name for, by number ("Unknown importance: 23"). The numbers are
the constants in Android's UsageEvents.java.

Every event is put in one of three classes by what it tells us:

    usage       a person did something: an app came to the foreground or left it,
                the device was unlocked, the person interacted with an app or a
                notification.
    state       the device changed state: screen on/off, lock screen shown,
                power off/on, configuration change.
    heartbeat   the device was on and logging, and nothing more: background
                events that happen whether or not anyone uses the device
                (standby bucket changes, incoming notifications, foreground
                services, ...).

A heartbeat is evidence that the device was alive. Its absence is weak evidence:
a sleeping device can go hours without one. The toolbox reports heartbeats as
evidence and applies no threshold to them.
"""
import re

# UsageEvents.java constants (manual, "Log Events defined in the Android System")
CODE_NAMES = {
    1: "Activity Resumed", 2: "Activity Paused", 3: "End of Day", 4: "Continue Previous Day",
    5: "Configuration Change", 6: "System Interaction", 7: "User Interaction", 8: "Shortcut Invocation",
    9: "Chooser Action", 10: "Notification Seen", 11: "Standby Bucket Changed", 12: "Notification Interruption",
    13: "Slice Pinned (private)", 14: "Slice Pinned", 15: "Screen Interactive", 16: "Screen Non-interactive",
    17: "Keyguard Shown", 18: "Keyguard Hidden", 19: "Foreground Service Start", 20: "Foreground Service Stop",
    21: "Continuing Foreground Service", 22: "Rollover Foreground Service", 23: "Activity Stopped",
    24: "Activity Destroyed", 25: "Flush to Disk", 26: "Device Shutdown", 27: "Device Startup",
    28: "User Unlocked", 29: "User Stopped", 30: "Locus ID Set", 31: "App Component Used",
}

# Old-format names for the same events
ALIASES = {"Move to Foreground": "Activity Resumed", "Move to Background": "Activity Paused"}

USAGE = {"Activity Resumed", "Activity Paused", "Activity Stopped", "Keyguard Hidden", "User Interaction",
         "Notification Seen", "Shortcut Invocation", "Chooser Action"}
STATE = {"Screen Interactive", "Screen Non-interactive", "Keyguard Shown", "Configuration Change",
         "Device Shutdown", "Device Startup", "User Unlocked", "User Stopped"}
# everything else is a heartbeat, including codes Android does not define (32, 10001, 10002)

_CODE = re.compile(r"^Unknown importance: (\d+)$")


def canonical_name(interaction_type):
    """'Unknown importance: 23' -> 'Activity Stopped'; 'Move to Foreground' -> 'Activity Resumed'."""
    it = str(interaction_type)
    m = _CODE.match(it)
    if m:
        return CODE_NAMES.get(int(m.group(1)), it)
    return ALIASES.get(it, it)


def event_class(interaction_type):
    name = canonical_name(interaction_type)
    if name in USAGE:
        return "usage"
    if name in STATE:
        return "state"
    return "heartbeat"


def classify_series(s):
    """Vectorised event_class for a pandas Series of interaction_type values."""
    uniq = {v: event_class(v) for v in s.dropna().unique()}
    return s.map(uniq).fillna("heartbeat")
