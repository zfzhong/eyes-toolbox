"""
Read app-level chunks and generate screen time for major/secondary apps. 
"""

import sys

from datetime import datetime

APP_NAME=0;TIME_START=1;TIME_END=2;DURATION=3;APP_LABEL=4

def is_overlaped(prev_chunk, curr_chunk):
    if curr_chunk[TIME_START] < prev_chunk[TIME_END]:
        return True
    
    return False

def get_time_diff_seconds(t1_str, t2_str):
        t1 = datetime.fromisoformat(t1_str)
        t2 = datetime.fromisoformat(t2_str)

        d = t2 - t1
        return d.total_seconds()


def get_diff_seconds(t1, t2):
    d = t2 - t1
    return d.total_seconds()

def create_new_chunk(chunk, start_time, end_time):
    duration = get_diff_seconds(start_time, end_time)
    app_name = chunk[APP_NAME]
    app_label = chunk[APP_LABEL]

    new_chunk = [app_name, start_time, end_time, duration, app_label]
    return new_chunk

class AppUsageChunks:
    def __init__(self, sorted_chunks):
        self.chunks = sorted_chunks

    def insert_chunk(self, i, chunk):
        self.chunks.insert(i, chunk)

    def separate_overlaped_chunks(self, out_csv_file):
        """
        Split app-level chunks into primary / secondary rows.

        Rule: at any instant, among all chunks that are running, the one that
        started most recently is PRIMARY; every other running chunk is
        SECONDARY for that instant. When the primary chunk ends, the most
        recently started chunk still running becomes primary again.

        Implemented as a sweep line over all chunk boundaries, so every second
        of every input chunk appears in exactly one output row, and the
        primary rows never overlap each other.
        """
        import heapq

        chunks = [c for c in self.chunks if c[TIME_END] > c[TIME_START]]
        # stable order: by start, then input order (later index wins ties)
        order = sorted(range(len(chunks)), key=lambda k: chunks[k][TIME_START])
        rank = {k: r for r, k in enumerate(order)}  # higher rank = started later

        events = []  # (time, kind, idx); kind 0 = end, 1 = start (ends first)
        for k, c in enumerate(chunks):
            events.append((c[TIME_START], 1, k))
            events.append((c[TIME_END], 0, k))
        events.sort(key=lambda e: (e[0], e[1], rank[e[2]]))

        rows = []            # (start, end, idx, is_primary)
        open_row = {}        # idx -> (row_start, is_primary)
        active = set()
        heap = []            # (-rank, idx), lazy deletion
        primary = None

        def close(k, t):
            s, is_p = open_row.pop(k)
            if t > s:
                rows.append((s, t, k, is_p))

        i = 0
        n = len(events)
        while i < n:
            t = events[i][0]
            started = []
            while i < n and events[i][0] == t:
                _, kind, k = events[i]
                if kind == 0:
                    active.discard(k)
                    close(k, t)
                else:
                    active.add(k)
                    heapq.heappush(heap, (-rank[k], k))
                    started.append(k)
                i += 1

            while heap and heap[0][1] not in active:
                heapq.heappop(heap)
            new_primary = heap[0][1] if heap else None

            if new_primary != primary:
                if primary is not None and primary in active:
                    close(primary, t)
                    open_row[primary] = (t, False)
                if new_primary is not None and new_primary in open_row:
                    close(new_primary, t)
                primary = new_primary

            for k in started:
                if k not in open_row:
                    open_row[k] = (t, k == primary)
            if primary is not None and primary not in open_row:
                open_row[primary] = (t, True)

        rows.sort(key=lambda r: (r[0], not r[3]))

        f = open(out_csv_file, 'w')
        f.write("app_package_name,resume_time,end_time,duration,secondary_duration,app_label\n")
        for s, e, k, is_p in rows:
            c = chunks[k]
            d = get_diff_seconds(s, e)
            if is_p:
                f.write("%s,%s,%s,%s,0,%s\n" % (c[APP_NAME], s, e, d, c[APP_LABEL]))
            else:
                f.write("%s,%s,%s,0,%s,%s\n" % (c[APP_NAME], s, e, d, c[APP_LABEL]))
        f.close()


def get_app_chunks(filename):
    chunks = []
    
    f = open(filename, 'r')

    # skip first line
    line = f.readline()

    line = f.readline()
    while line:
        line = line.strip()                
        tokens = line.split(',')

        app_name = tokens[APP_NAME].strip()
        time_start = datetime.fromisoformat(tokens[TIME_START].strip())
        time_end = datetime.fromisoformat(tokens[TIME_END].strip())
        duration = tokens[DURATION].strip()
        app_label = tokens[APP_LABEL].strip()
        
        curr_chunk = [app_name, time_start, time_end, float(duration),app_label]

        chunks.append(curr_chunk)

        line = f.readline()

    f.close()

    return chunks


def get_overlap_chunks(sorted_chunks, out1, interval_threshold):
    prev_chunk = None

    f1 = open(out1, 'w')
    f1.write("app_package_name,resume_time,end_time,duration,secondary_duration,note,app_label\n")

    prev_chunk = sorted_chunks[0]
    prev_start = prev_chunk[TIME_START]
 
    for i in range(1, len(sorted_chunks)):
        curr_chunk = sorted_chunks[i]

        # take care of the end_time of the previous chunk
        if curr_chunk[TIME_START] >= prev_chunk[TIME_END]:
            duration = get_diff_seconds(prev_start, prev_chunk[TIME_END])
            f1.write("%s,%s,%s,%s,0,,%s\n" % (prev_chunk[APP_NAME], prev_start, prev_chunk[TIME_END], duration, prev_chunk[APP_LABEL]))
        elif get_diff_seconds(curr_chunk[TIME_START], prev_chunk[TIME_END]) < interval_threshold:
            duration = get_diff_seconds(prev_start, curr_chunk[TIME_START])
            f1.write("%s,%s,%s,%s,0,,%s\n" % (prev_chunk[APP_NAME], prev_start,curr_chunk[TIME_START],duration, prev_chunk[APP_LABEL]))
        else:
            # this is the case where we have "secondary" screen time
            
            if curr_chunk[TIME_START] > prev_start:
                # in theory, curr_chunk[TIME_START] coud be a lot less than prev_start, but
                # we dont deal with this case for now

                primary_duration = get_diff_seconds(prev_start, curr_chunk[TIME_START])
                f1.write("%s,%s,%s,%s,0,,%s\n" % (prev_chunk[APP_NAME], prev_start,curr_chunk[TIME_START],primary_duration,prev_chunk[APP_LABEL]))

            # calculate the 'secondary' screen time
            if curr_chunk[TIME_END] >= prev_chunk[TIME_END] or get_diff_seconds(curr_chunk[TIME_END], prev_chunk[TIME_END]) < interval_threshold:
                secondary_duration = get_diff_seconds(curr_chunk[TIME_START], prev_chunk[TIME_END])
                f1.write("%s,%s,%s,0,%s,,%s\n" % (prev_chunk[APP_NAME], curr_chunk[TIME_START], prev_chunk[TIME_END], secondary_duration,prev_chunk[APP_LABEL]))
            else:
                secondary_duration = get_diff_seconds(curr_chunk[TIME_START], curr_chunk[TIME_END])
                f1.write("%s,%s,%s,0,%s,nested,%s\n" % (prev_chunk[APP_NAME], curr_chunk[TIME_START], curr_chunk[TIME_END], secondary_duration,prev_chunk[APP_LABEL]))

                # primary screen time of the current App -- this time is the same as the secondary screen time of the previous App.
                f1.write("%s,%s,%s,%s,0,,%s\n" % (curr_chunk[APP_NAME], curr_chunk[TIME_START], curr_chunk[TIME_END], secondary_duration,curr_chunk[APP_LABEL]))

                prev_start = curr_chunk[TIME_END]
                continue

        prev_chunk = curr_chunk
        prev_start = prev_chunk[TIME_START]

    # write the last chunk data
    f1.write("%s,%s,%s,%s,0,%s\n" % (prev_chunk[APP_NAME], prev_chunk[TIME_START], prev_chunk[TIME_END], prev_chunk[DURATION], prev_chunk[APP_LABEL]))    

    f1.close()

import os

def dump_sorted_data(sorted_chunks, out_filename):
    dir_name = os.path.dirname(out_filename)
    file_name = os.path.basename(out_filename)

    tokens = file_name.split('.')

    prefix = tokens[0].replace(' ', '_')
    sorted_filename = "%s/%s_sorted.csv" % (dir_name, prefix)

    f = open(sorted_filename, 'w')

    for i in range(0, len(sorted_chunks)):
        chunk = sorted_chunks[i]
        f.write("%s,%s,%s,%s,%s\n" % (chunk[APP_NAME], chunk[TIME_START], chunk[TIME_END], chunk[DURATION], chunk[APP_LABEL]))

    f.close()


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage:", sys.argv[0], "<app_chunk_file><interval_threshold><output_file>")
        print("Example:", sys.argv[0], "4075_app_1.csv 2 4075_2nd_nested.csv")
        
        sys.exit(1)

    input_file = sys.argv[1]
    interval_threshold = int(sys.argv[2])
    out_file = sys.argv[3]

    app_chunks = get_app_chunks(input_file)

    sorted_chunks = sorted(app_chunks, key=lambda x: x[1])

    #dump_sorted_data(sorted_chunks, out_file)

    auc = AppUsageChunks(sorted_chunks=sorted_chunks)
    auc.separate_overlaped_chunks(out_csv_file=out_file)

    #get_overlap_chunks(sorted_chunks, out_file, interval_threshold)



    
    
