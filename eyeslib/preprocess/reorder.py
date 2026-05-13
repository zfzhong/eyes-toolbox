import pandas as pd

resume_states = ['Activity Resumed', 'Move to Foreground']
pause_states = ['Activity Paused', 'Move to Background']

def reorder_pause_resume(infile, outfile):
    # 1. Load & parse, sort
    df = pd.read_csv(infile, low_memory=False)
    df['event_timestamp'] = pd.to_datetime(df['event_timestamp'], format='mixed', utc=True)


    # 2. Build a new list of records, check where two consecutive pause/resume events happen at the same time
    out_records = []
    prev_record = None

    for record in df.to_dict('records'):
        if prev_record is None:
            out_records.append(record)
            prev_record = record
            continue
        
        prev_ts = prev_record['event_timestamp']
        curr_ts = record['event_timestamp']
        #print(prev_ts, curr_ts)

        prev_app_name = prev_record['app_package_name']
        curr_app_name = record['app_package_name']

        prev_state = prev_record['interaction_type']
        curr_state = record['interaction_type']

        if prev_app_name == curr_app_name and curr_ts == prev_ts and prev_state in pause_states and curr_state in resume_states:
            #print("-----")
            #print(prev_record)
            #print(record)
            out_records.insert(-1, record)
        else:    
            out_records.append(record)
        
        prev_record = record

    # 3. Reconstruct DataFrame and ensure timestamp column is datetime
    df_reordered = pd.DataFrame(out_records)
    df_reordered['event_timestamp'] = pd.to_datetime(df_reordered['event_timestamp'])

    # 4. (Optional) write back out
    df_reordered.to_csv(outfile, index=False)

import os, sys
from pathlib import Path
import re

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage:", sys.argv[0], "<chronicle_log_dir>")
        sys.exit(1)

    directory = Path(sys.argv[1]+'/processed')

    csv_files = [f for f in directory.glob("*.csv") if re.search(r'uniq.csv$', f.name)]

    for infile in csv_files:
        dir_name = os.path.dirname(infile)
        file_name = os.path.basename(infile)

        tokens = file_name.split('.')

        prefix = tokens[0].replace(' ', '_')
        outfile = "%s/%s_reordered.csv" % (dir_name, prefix)

        print(outfile)

        reorder_pause_resume(infile, outfile)