"""Load an EyesApp export into the toolbox.

EyesApp (github zfzhong/eyesapp) reads Android's UsageStatsManager on a test device and writes
<device>-<protocol>-EVENT-<from>-to-<to>.csv with the columns
    app_package_name, app_class_name, interaction_type, event_timestamp (ms since epoch), timezone, tz_offset,
    event_action, event_category
It keeps what Chronicle drops: the screen (activity class) of each app event and the extras of User Interaction
(event_action start / stop / tap with event_category, e.g. android.media = play / pause).

convert() writes the same events in the layout the toolbox reads (the *_sorted_uniq_reordered.csv of a processed
Chronicle folder), with the extra columns kept at the end, so the device-state and profile runners work unchanged:

    python -m eyeslib.preprocess.eyesapp <EVENT csv> [--out <folder>] [--participant samsung01]

writes <folder>/processed/<participant>_Android_EyesApp_<from>-to-<to>_sorted_uniq_reordered.csv
(<folder> defaults to the folder of the export). Reference traces from a test phone are ground truth for the
sub-tracks (small window, car projection, audio, calls); they are not study data.
"""
import argparse, os, re
import pandas as pd

# EyesApp spellings -> the names Chronicle uses. Types 10 / 11 / 12 / 13 / 14 have no name in EyesApp yet.
NAMES = {
    "Screen Non Interactive": "Screen Non-interactive",
    "Unknown importance: 10": "Notification Seen",
    "Unknown importance: 11": "Standby Bucket Changed",
    "Unknown importance: 12": "Notification Interruption",
    "Unknown importance: 13": "Slice Pinned (private)",
    "Unknown importance: 14": "Slice Pinned",
}
OUT_COLS = ["study_id", "participant_id", "app_package_name", "interaction_type", "event_type", "event_timestamp",
            "timezone", "username", "application_label", "uploaded_at", "app_class_name", "event_action", "event_category"]


def read(event_csv):
    """The export as a frame with Chronicle's event names, UTC timestamps, and the three extra columns."""
    d = pd.read_csv(event_csv, dtype=str, keep_default_na=False)
    d["interaction_type"] = d["interaction_type"].map(lambda v: NAMES.get(v, v))
    d["app_class_name"] = d["app_class_name"].replace("null", "")
    ms = pd.to_numeric(d["event_timestamp"], errors="coerce")
    d = d[ms.notna()].copy()
    d["_ms"] = ms[ms.notna()].astype("int64")
    d = d.sort_values("_ms", kind="mergesort").drop_duplicates(
        ["app_package_name", "app_class_name", "interaction_type", "_ms", "event_action"])
    d["event_timestamp"] = pd.to_datetime(d["_ms"], unit="ms", utc=True).dt.strftime("%Y-%m-%d %H:%M:%S.%f+00:00")
    return d.drop(columns="_ms").reset_index(drop=True)


def convert(event_csv, out_dir=None, participant=None):
    d = read(event_csv)
    base = os.path.basename(event_csv)
    m = re.match(r"(?P<dev>.+?)-(?P<proto>.+?)-EVENT-(?P<span>.+)\.csv$", base)
    dev = participant or (m.group("dev") if m else "device")
    span = m.group("span") if m else "export"
    d["study_id"], d["participant_id"] = "eyesapp-test", dev + "_Android"
    d["event_type"] = d["username"] = d["application_label"] = d["uploaded_at"] = ""
    proc = os.path.join(out_dir or os.path.dirname(os.path.abspath(event_csv)), "processed")
    os.makedirs(proc, exist_ok=True)
    out = os.path.join(proc, f"{dev}_Android_EyesApp_{span}_sorted_uniq_reordered.csv")
    d[OUT_COLS].to_csv(out, index=False)
    return out, len(d)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("event_csv")
    ap.add_argument("--out", default=None)
    ap.add_argument("--participant", default=None)
    a = ap.parse_args(argv)
    out, n = convert(a.event_csv, a.out, a.participant)
    print(f"{n} events -> {out}")


if __name__ == "__main__":
    main()
