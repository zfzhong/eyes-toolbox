"""
Car display (Android Auto) (see the manual, "Car Display").

With Android Auto, the phone drives a second screen: the car's. Apps shown there
(navigation above all) come to the foreground while the phone itself stays locked.
Their time is real use, but not phone screen time, so it is counted in its own
category instead of being dropped.

Rule (no threshold): an app period is on the car display when, at its start,
    - Android Auto is connected: its foreground service is running (the last
      Foreground Service Start / Stop of com.google.android.projection.gearhead
      at or before the start is a Start), and
    - the phone is locked: the last Keyguard Shown / Hidden event strictly before
      the start is Keyguard Shown.
Apps opened on the unlocked phone while Android Auto is connected (for example,
by a passenger) stay on the phone display.
"""
import numpy as np

AA_PACKAGE = "com.google.android.projection.gearhead"
FGS_START = {"Foreground Service Start", "Unknown importance: 19"}
FGS_STOP = {"Foreground Service Stop", "Unknown importance: 20"}
KG_SHOWN = {"Keyguard Shown", "Unknown importance: 17"}
KG_HIDDEN = {"Keyguard Hidden", "Unknown importance: 18"}


def display_state(df_all, t_col="t"):
    """Keyguard and Android Auto timelines from a log sorted by time.
    Returns (kg_t, kg_locked, aa_t, aa_on) as numpy arrays (datetime64[ns] UTC, bool)."""
    it = df_all["interaction_type"]
    kg = df_all[it.isin(KG_SHOWN | KG_HIDDEN)]
    aa = df_all[(df_all["app_package_name"] == AA_PACKAGE) & it.isin(FGS_START | FGS_STOP)]
    return (kg[t_col].values, kg["interaction_type"].isin(KG_SHOWN).to_numpy(),
            aa[t_col].values, aa["interaction_type"].isin(FGS_START).to_numpy())


def displays(starts, state):
    """'car' or 'phone' for each start time (datetime64[ns] UTC array)."""
    kg_t, kg_locked, aa_t, aa_on = state
    starts = np.asarray(starts, dtype="datetime64[ns]")
    out = np.full(len(starts), "phone", dtype=object)
    if not len(starts) or not len(aa_t) or not len(kg_t):
        return out
    k = np.searchsorted(kg_t, starts, "left") - 1        # last keyguard event strictly before
    j = np.searchsorted(aa_t, starts, "right") - 1       # last Android Auto service event at or before
    locked = (k >= 0) & kg_locked[np.maximum(k, 0)]
    connected = (j >= 0) & aa_on[np.maximum(j, 0)]
    out[locked & connected] = "car"
    return out
