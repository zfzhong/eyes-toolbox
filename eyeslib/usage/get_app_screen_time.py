"""
Read activity-level blocks and generate screen time for each App. 
"""

import csv
import sys

from datetime import datetime

APP_NAME = "app_package_name"
RESUMED = "resume_time"
PAUSED = "pause_time"
STOPPED = "stop_time"
APP_LABEL = "app_label"

def get_time_diff_seconds(t1_str, t2_str):
        t1 = datetime.fromisoformat(t1_str)
        t2 = datetime.fromisoformat(t2_str)

        d = t2 - t1
        return d.total_seconds()

def normalize_cell(value):
    if value is None:
        return None
    return str(value).replace("\r", " ").replace("\n", " ").strip()

def iter_activity_rows(filename):
    """
    Yield normalized activity rows.

    Newer files are proper CSV. Older files may contain unquoted commas/newlines in
    app labels, which splits one logical row across multiple physical lines.
    """
    with open(filename, "r", encoding="utf-8", errors="replace", newline="") as f:
        header_line = f.readline()
        if not header_line:
            return

        header = [cell.strip() for cell in header_line.strip().split(",")]
        expected_columns = len(header)
        if expected_columns == 0:
            return

        buffer = ""
        for raw_line in f:
            line = raw_line.rstrip("\n")
            buffer = f"{buffer}\n{line}" if buffer else line
            tokens = buffer.split(",")
            if len(tokens) < expected_columns:
                continue

            record = {}
            for idx, name in enumerate(header[:7]):
                record[name] = normalize_cell(tokens[idx])

            record[header[7]] = normalize_cell(",".join(tokens[7:-1]))
            record[header[8]] = normalize_cell(tokens[-1])
            yield record
            buffer = ""

        if buffer:
            tokens = buffer.split(",")
            if len(tokens) >= expected_columns:
                record = {}
                for idx, name in enumerate(header[:7]):
                    record[name] = normalize_cell(tokens[idx])
                record[header[7]] = normalize_cell(",".join(tokens[7:-1]))
                record[header[8]] = normalize_cell(tokens[-1])
                yield record

def get_app_chunks(filename):
    chunks = {}

    for row in iter_activity_rows(filename):
        app_name = normalize_cell(row.get(APP_NAME))
        if not app_name:
            continue

        t1_str = normalize_cell(row.get(RESUMED))
        if t1_str == '' or t1_str == 'None':
            continue

        start_t = datetime.fromisoformat(t1_str)

        t2_str = normalize_cell(row.get(STOPPED))
        if t2_str == '' or t2_str == 'None':
            t2_str = normalize_cell(row.get(PAUSED))
            if t2_str == '' or t2_str == 'None':
                continue

        end_t = datetime.fromisoformat(t2_str)
        
        curr_chunk = {'start': start_t, 'end': end_t, 'label': normalize_cell(row.get(APP_LABEL))}

        if app_name in chunks:
            chunks[app_name].append(curr_chunk)
        else:
            chunks[app_name] = [curr_chunk]

    return chunks


def merge_app_chunks(chunks):
    merged_chunks = {}
    for app_name in chunks:
        app_chunks = chunks[app_name]
        sorted_chunks = sorted(app_chunks, key=lambda x: x['start'])

        curr_chunk = sorted_chunks[0]
        merged_chunks[app_name] = []

        i = 1
        while i < len(sorted_chunks):
            chunk = sorted_chunks[i]
            if chunk['start'] <= curr_chunk['end']:
                curr_chunk['end'] = max(chunk['end'], curr_chunk['end'])
            else:
                merged_chunks[app_name].append(curr_chunk)
                curr_chunk = sorted_chunks[i]

            i += 1

        merged_chunks[app_name].append(curr_chunk)
                
    return merged_chunks

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage:", sys.argv[0], "<activity_block_file>")
        sys.exit(1)

    filename = sys.argv[1]

    chunks = get_app_chunks(filename)
    merged_chunks = merge_app_chunks(chunks)

    
    print("app_package_name,resume_time,end_time,duration,app_label")
    screen_times = []
    for app_name in merged_chunks:
        #print("++++ %s ++++" % app_name)
        total = 0
        for chunk in merged_chunks[app_name]:
            t1 = chunk['start']
            t2 = chunk['end']
            delta = t2 - t1 
            sec = delta.total_seconds()
            print("%s,%s,%s,%s,%s" % (app_name, t1, t2, sec, chunk['label']))

            total += sec

        #print("%.2f,\t%s" % (total, app_name))
        screen_times.append([app_name, total])

"""
    sorted_list = sorted(screen_times, key=lambda x: x[1])

    for item in sorted_list:
        print("%.2f,\t%s" % (item[1], item[0]))
"""

    
    
