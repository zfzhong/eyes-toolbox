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
        f = open(out_csv_file, 'w')
        f.write("app_package_name,resume_time,end_time,duration,secondary_duration,app_label\n")

        working_on_stack = False
        stack = []
        i = 0
        while i < len(self.chunks):
            curr_chunk = self.chunks[i]

            if len(stack) <= 0:
                stack.append(curr_chunk)
            elif is_overlaped(stack[-1], curr_chunk):
                stack.append(curr_chunk)
            else:
                # work on the stack to identify the overlaped time frame
                while len(stack) > 0:
                    stack_chunk = stack.pop()
                    #print('top stack', stack_chunk[TIME_START], stack_chunk[TIME_END])

                    if working_on_stack is False:    
                        # the top stack chunk
                        working_on_stack = True

                        start_time = stack_chunk[TIME_START]
                        end_time = stack_chunk[TIME_END]
                    
                        # print primary
                        duration = get_diff_seconds(start_time, end_time)
                        f.write("%s,%s,%s,%s,0,%s\n" % (stack_chunk[APP_NAME], start_time, end_time, duration, stack_chunk[APP_LABEL]))
                    else:                    
                        if stack_chunk[TIME_START] < start_time:
                            # print primary
                            duration = get_diff_seconds(stack_chunk[TIME_START], start_time)
                            f.write("%s,%s,%s,%s,0,%s\n" % (stack_chunk[APP_NAME],stack_chunk[TIME_START],start_time,duration,stack_chunk[APP_LABEL]))

                        if stack_chunk[TIME_END] <= end_time:
                            # print secondary
                            duration = get_diff_seconds(start_time, stack_chunk[TIME_END])
                            f.write("%s,%s,%s,0,%s,%s\n" % (stack_chunk[APP_NAME],start_time,stack_chunk[TIME_END],duration,stack_chunk[APP_LABEL]))
                        else:
                            # print secondary
                            duration = get_diff_seconds(start_time, end_time)
                            f.write("%s,%s,%s,0,%s,%s\n" % (stack_chunk[APP_NAME],start_time,end_time,duration,stack_chunk[APP_LABEL]))
                        
                            # create a new chunk (leftover from curr_stack_chunk)
                            new_chunk = create_new_chunk(stack_chunk, end_time, stack_chunk[TIME_END])
                            #print("new chunk", new_chunk)
                            self.insert_chunk(i, new_chunk)

                        start_time = stack_chunk[TIME_START]

                working_on_stack = False

            i += 1
        
        # clean up the stack
        while len(stack) > 0:
            stack_chunk = stack.pop()
            
            if working_on_stack is False:    
                # the top stack chunk
                working_on_stack = True

                start_time = stack_chunk[TIME_START]
                end_time = stack_chunk[TIME_END]
                    
                # print primary
                duration = get_diff_seconds(start_time, end_time)
                f.write("%s,%s,%s,%s,0,%s\n" % (stack_chunk[APP_NAME], start_time, end_time, duration, stack_chunk[APP_LABEL]))
            else:                    
                if stack_chunk[TIME_START] < start_time:
                    # print primary
                    duration = get_diff_seconds(stack_chunk[TIME_START], start_time)
                    f.write("%s,%s,%s,%s,0,%s\n" % (stack_chunk[APP_NAME],stack_chunk[TIME_START],start_time,duration,stack_chunk[APP_LABEL]))

                if stack_chunk[TIME_END] <= end_time:
                    # print secondary
                    duration = get_diff_seconds(start_time, stack_chunk[TIME_END])
                    f.write("%s,%s,%s,0,%s,%s\n" % (stack_chunk[APP_NAME],start_time,stack_chunk[TIME_END],duration,stack_chunk[APP_LABEL]))
                else:
                    # print secondary
                    duration = get_diff_seconds(start_time, end_time)
                    f.write("%s,%s,%s,0,%s,%s\n" % (stack_chunk[APP_NAME],start_time,end_time,duration,stack_chunk[APP_LABEL]))
                        
                    # print primary (leftover from curr_stack_chunk)
                    duration = get_diff_seconds(end_time, stack_chunk[TIME_END])
                    f.write("%s,%s,%s,%s,0,%s\n" % (stack_chunk[APP_NAME],end_time,stack_chunk[TIME_END],duration,stack_chunk[APP_LABEL]))
                    end_time = stack_chunk[TIME_END]
                    
            start_time = stack_chunk[TIME_START]

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



    
    
