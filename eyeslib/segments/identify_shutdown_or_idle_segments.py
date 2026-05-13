import pandas as pd
import os, sys
from pathlib import Path
import re

"""
Given a time-series data file, we want to detect the following:
1) the device idle (screen off/screen protection) time 
2) the device shutdown time
3) unknown long gaps (for example, gaps which last more than 1 hours)


* Output data format:
State, start_time, end_time, duration, interaction_type
IDLE, t1, t2, t2-t1, 'Screen Non-Interactive'
SHUTDOWN, t1, t2, t2-t1, 'Device Shutdown'
GAP, t1, t2, t2-t1, 'gap'

* Design:
The 3 possible states of a device: RUNNING, IDLE, SHUTDOWN.
At any moment, the device can only stay in one of the 3 states.

* Suggestion:
we should have separate logics to:
1) detect shutdown time (detect_shutdown_segment.py)
2) detect idle time (detect_idle_segment.py)
3) detect large gaps (detect_gap_segment.py)

And we visualize the three kinds of segments (with different color) to check if 
there exists overlaps. One challenge is that sometimes a shutdown/idle time segment is 
classified as an App running time segement (because of lacking of shutdown/idle events 
to help identify the segment).


* Gap detection
There could be large gaps during a RUNNING or IDLE state. It could be that the device
actually entered SHUTDOWN state in that gap period but the transition events (shutdown/startup) 
was not logged.

"""

RUNNING='RUNNING'
IDLE='IDLE'
SHUTDOWN='SHUTDOWN'

code2event = {
    'Device Startup': "Device Startup",
    'Unknown importance: 27': "Device Startup",
    'User Unlocked': 'User Unlocked',
    'Unknown importance: 28': 'User Unlocked', 
    'Device Shutdown': 'Device Shutdown', 
    'Unknown importance: 26': 'Device Shutdown',
    'User Stopped': 'User Stopped',
    'Unknown importance: 29': 'User Stopped',
    'Screen Interactive': 'Screen Interactive',
    'Unknown importance: 15': 'Screen Interactive',
    'Keyguard Hidden': 'Keyguard Hidden',
    'Unknown importance: 18': 'Keyguard Hidden',
    'Screen Non-interactive': 'Screen Non-interactive', 
    'Unknown importance: 16': 'Screen Non-interactive',
    'Keyguard Shown': 'Keyguard Shown',
    'Unknown importance: 17': 'Keyguard Shown', 
}

start_reboot_states = [
    'Device Startup', 
    'Unknown importance: 27', # device restart
    'User Unlocked',
    'Unknown importance: 28', 
]

end_reboot_states = [
    'Device Shutdown', 
    'Unknown importance: 26', # device shutdown
    'User Stopped',
    'Unknown importance: 29'
]

reboot_states = start_reboot_states + end_reboot_states

start_idle_states = [
    'Screen Interactive',
    'Unknown importance: 15', # scren interactive
    'Keyguard Hidden',
    'Unknown importance: 18' 
]

end_idle_states = [
    'Screen Non-interactive', 
    'Unknown importance: 16', # screen non interactive
    'Keyguard Shown',
    'Unknown importance: 17',  
]

idle_states = start_idle_states + end_idle_states

event2state = {
    SHUTDOWN: reboot_states,
    IDLE: idle_states
}

PROXIMITY_TIME = pd.Timedelta(seconds=2) # 2 seconds

idle_event_indicators = [
    'Unknown importance: 11'
]

IDLE_NUM = 4


def get_shutdown_or_idle_events(infile, outfile, event):
    # 1. Load & parse, sort
    df = pd.read_csv(infile, low_memory=False)
    df['event_timestamp'] = pd.to_datetime(df['event_timestamp'], format='mixed', utc=True)

    out_records = []
    records = df.to_dict('records')

    for i in range(0, len(records)):
        record = records[i]

        ia_type = record['interaction_type']

        if ia_type in event2state[event]:
            #print("%s,%s,%s,%s" %(record['app_package_name'],ia_type, record['event_timestamp'], code2event[ia_type]))
            record['event_name'] = code2event[ia_type]
            out_records.append(record)

    df_out = pd.DataFrame(out_records)

    dir_path = os.path.dirname(outfile)
    os.makedirs(dir_path, exist_ok=True)

    df_out.to_csv(outfile, index=False)


def get_filename_prefix(filename):
    tokens = filename.split('_')
    return tokens[0] + '_' + tokens[1]



if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage:", sys.argv[0], "<infile><SHUTDOWN/IDLE><outfile>")
        sys.exit(1)

    infile = sys.argv[1]
    eventcode = sys.argv[2]
    outfile = sys.argv[3]

    get_shutdown_or_idle_events(infile, outfile, eventcode)