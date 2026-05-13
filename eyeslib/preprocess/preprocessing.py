"""
This program does the following:
1) sort the original chronicle log data based on the 'event_timestamp' column.
2) filter some rows that has 'unknown importance: i', given 'i' is an input number. 
3) identify the start and end of the usage of the device, and split the data and write them into several new files.
"""

from pathlib import Path

import matplotlib.pyplot as plt

import pandas as pd
from pandas.errors import EmptyDataError
import sys

start_states = ['Device Startup', 'Unknown importance: 27']
stop_states = ['Device Shutdown', 'Unknown importance: 26']


def get_importance_numbers(s):
    tokens = s.split(',')
    numbers = [int(x) for x in tokens]

    return numbers

def sort_data_file(infile, outfile):
    # Read the CSV (first row is treated as header by default)
    df = pd.read_csv(infile)

    df['event_timestamp'] = pd.to_datetime(df['event_timestamp'], format='mixed', utc=True)

    # Sort by 'event_timestamp'
    df_sorted = df.sort_values(by=['event_timestamp', 'interaction_type'])

    # Save back to CSV
    df_sorted.to_csv(outfile, index=False)

def sort_and_filter(infile, outfile, numbers, max_hours):
    # Read the CSV (first row is treated as header by default)
    df = pd.read_csv(infile)

    df['event_timestamp'] = pd.to_datetime(df['event_timestamp'], format='mixed', utc=True)

    # filtering
    unwanted_values = [f"Unknown importance: {n}" for n in numbers]
    df = df[~df['interaction_type'].isin(unwanted_values)]

    # Sort by 'event_timestamp'
    df_sorted = df.sort_values(by=['event_timestamp', 'interaction_type'])

    # Save back to CSV
    df_sorted.to_csv(outfile, index=False)

    # split the data into separate files
    chunks = []
    curr_chunk = []
    in_chunk = False

    #df_sorted['datetime'] = pd.to_datetime(df_sorted['event_timestamp'], format='mixed', utc=True)
    #df_sorted['datetime'] = pd.to_datetime(df_sorted['datetime'], utc=True)

    # Convert to milliseconds since epoch
    df_sorted['timestamp'] = df_sorted['event_timestamp'].astype('int64') // 1_000_000
    
    prev_ts = df_sorted.iloc[0]['timestamp']

    for i, row in df_sorted.iterrows():
        interaction = row['interaction_type']
        curr_ts = row['timestamp']

        if not in_chunk:
            curr_chunk = [row.to_dict()]
            in_chunk = True

            if interaction in stop_states:
                in_chunk = False
        else:
            if interaction in start_states or curr_ts - prev_ts >= max_hours*3600000:
                """
                End the current chunk, and then start a new chunk.
                """
                chunks.append(pd.DataFrame(curr_chunk))
                curr_chunk = [row.to_dict()]
            else:
                curr_chunk.append(row.to_dict())
                if interaction in stop_states:
                    """
                    End the current chunk.
                    """
                    chunks.append(pd.DataFrame(curr_chunk))
                    in_chunk = False

        prev_ts = curr_ts

    # Take care of the last chunk
    if in_chunk:
        chunks.append(pd.DataFrame(curr_chunk))

    plt.figure()


    file_path = Path(os.path.dirname(infile))
    file_name = os.path.basename(infile)

    parts = list(file_path.parts)
    # Replace 'raw' with 'processed'
    parts[-1] = 'processed'
    processed_path = Path(*parts)

    tokens = file_name.split('.')

    i = 1
    for idx, chunk_df in enumerate(chunks):
        t1,t2 = chunk_df.iloc[0]['timestamp'], chunk_df.iloc[-1]['timestamp']
        
        if t2 - t1 >= 1000:
            prefix = tokens[0].replace(' ', '_')
            filename = processed_path / ("%s_%d.csv" % (prefix,i))

            if not processed_path.exists():
                processed_path.mkdir(parents=True, exist_ok=True)
            

            chunk_df.to_csv(filename, index=False)
            print("Saved data into file: %s" % filename)

            if i % 2 == 0:
                color = 'r'
            else:
                color = 'b'

            plt.plot([chunk_df.iloc[0]['event_timestamp'], chunk_df.iloc[-1]['event_timestamp']],[1,1], color=color)

            if chunk_df.iloc[0]['interaction_type'] in start_states:
                x,y = chunk_df.iloc[0]['event_timestamp'], 1
                plt.scatter(x, y, color='orange', s=5)
                plt.text(x, y, 'S', fontsize=8, ha='center', va='bottom')

            if chunk_df.iloc[-1]['interaction_type'] in stop_states:
                x,y = chunk_df.iloc[-1]['event_timestamp'], 1
                plt.scatter(x, y, color='black', s=5)
                plt.text(x, y, 'E', fontsize=8, ha='center', va='bottom')

            plt.text(chunk_df.iloc[0]['event_timestamp'], 0.9, str(i), fontsize=8, ha='center', va='top')
            plt.ylim(0.5,1.5)


            i += 1

    #plt.show()            
    
import os

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:", sys.argv[0], "<chronicle_log_file>")
        sys.exit(1)

    filename = sys.argv[1]

    dir_name = os.path.dirname(filename)
    file_name = os.path.basename(filename)

    tokens = file_name.split('.')

    #file_path = os.path.dirname(filename)
    #file_name = os.path.basename(filename)

    #print(file_path)
    #print(file_name)

    prefix = tokens[0].replace(' ', '_')
    outfile = "%s/processed/%s_sorted.csv" % (dir_name, prefix)

    dir_path = os.path.dirname(outfile)
    os.makedirs(dir_path, exist_ok=True)

    if os.path.getsize(filename) == 0:
        print("Skipping empty chronicle file: %s" % filename)
        sys.exit(0)

    try:
        sort_data_file(filename, outfile)
        print("Saved data into a new file: %s" % outfile)
    except EmptyDataError:
        print("Skipping chronicle file with no parseable CSV content: %s" % filename)
        sys.exit(0)


