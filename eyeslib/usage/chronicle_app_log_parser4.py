import sys
import pandas as pd

from datetime import datetime
from collections import deque
import csv

# choronicle log file format
STUDY_ID=0;PART_ID=1;APP_NAME=2;INT_TYPE=3;EVENT_TYPE=4;EVENT_TS=5;TIME_ZONE=6;USER_NAME=7;APP_LABEL=8;UPLOAD_TS=9

MTF = 'Move to Foreground'
MTB = 'Move to Background'

MAR = 'MissingActivityResumed'
NPI = 'NextBlockPausedInference'
NSI = 'NextBlockStoppedInference'
MST = 'MissingStop'

MPB = 'MatchingPreviousBlock'
MCB = 'MatchingCurrentBlock'

AKD = 'AppKilled'
SSD = 'SystemShutDown'
SNI = 'ScreenNonInteractive'

anomaly_states = [MAR, NPI, NSI, AKD, SSD]


reset_states = ['Screen Non-interactive', 'Unknown importance: 16']
background_states = ['Move to Background', 'Activity Paused']
foreground_states = ['Move to Foreground', 'Activity Resumed']

# todo: we should also add 'screen non-interactive' here:
stop_states = [
    'Activity Stopped', 
    'Unknown importance: 23'
    ]

reboot_states = [
    'Device Shutdown', 
    'Device Startup', 
    #'Gap Identified', # huge gaps, user configurable 
    #'Idle State', # device idale state (power saving mode)
    #'Unknown importance: 16', # screen non interactive
    #'Screen Non-interactive',
    'Unknown importance: 26', # device shutdown
    'Unknown importance: 27', # device restart
    'Unknown importance: 28', # user unlocked
    'Unknown importance: 29', # user stopped
    #'Unknown importance: 18', # Keyguard shown
    #'Keyguard Hidden',
    ]



class ChronicleLog:
    def __init__(self, line):
        tokens = [x.strip() for x in line.split(',')]
        self.study_id = tokens[STUDY_ID]
        self.participant_id = tokens[PART_ID]
        self.app_package_name = tokens[APP_NAME]
        self.interaction_type = tokens[INT_TYPE]
        self.event_type = tokens[EVENT_TYPE]
        self.event_timestamp = tokens[EVENT_TS]
        self.timezone = tokens[TIME_ZONE]
        self.username = tokens[USER_NAME]
        self.application_label = tokens[APP_LABEL]
        self.uploaded_at = tokens[UPLOAD_TS]

    def __str__(self):
        return ','.join([
            self.study_id, self.participant_id, self.app_package_name, self.interaction_type, self.event_type, 
            self.event_timestamp, self.timezone, self.username, self.application_label, self.uploaded_at
            ])

class ActivityBlock:
    def __init__(self, app_name=None, time_resume=None, resume_event=None, time_pause=None, pause_event=None, time_stop=None, stop_event=None, app_label=None, log_id=0):
        self.app_name = app_name

        self.time_resume = time_resume
        self.resume_event = resume_event

        self.time_pause = time_pause
        self.pause_event = pause_event

        self.time_stop = time_stop
        self.stop_event = stop_event 

        self.app_label = app_label

        self.log_id = log_id

        self.next = None

    def __str__(self):
        #duration = self.duration()
        t1,t2,t3 = self.time_resume, self.time_pause, self.time_stop
        e1,e2,e3 = self.resume_event, self.pause_event, self.stop_event

        return "%s,%s,%s,%s,%s,%s,%s,%s" % (self.app_name, t1,e1, t2,e2, t3,e3, self.app_label)
    
    def is_resumed(self):
        return self.time_resume != None and self.time_pause == None and self.time_stop == None
    
    def is_stopped(self):
        #if self.resume_event == MTF:
        #    return self.pause_event != None
        
        return self.stop_event != None
    
    def is_complete(self):
        #if self.resume_event == MTF:
        #    return self.time_resume != None and self.time_pause != None
        
        return self.time_resume != None and self.time_pause != None and self.time_stop != None
    
    def duration(self, struct_logic=True):
        """
        duration in seconds
        """
        if not self.time_resume:
            return 0
        
        if not struct_logic:
            """
            Use time_resume - time_pause as the duration.
            """
            if self.time_resume and self.time_pause:
                return get_time_diff_seconds(self.time_resume, self.time_pause)
            else:
                return 0

        #if self.resume_event == MTF:
            """ Old log files """
            """
            if self.time_resume and self.time_pause:
                return get_time_diff_seconds(self.time_resume, self.time_pause)
            elif self.time_resume:
                # Find the next block that has a different app_name, using the resume_time to calculate duration
                next_block = self.next
                
                if next_block:
                    self.time_pause = next_block.time_resume

                if self.time_pause:    
                    return get_time_diff_seconds(self.time_resume, self.time_pause)
            """
        if True:
            """" new log files """
            if self.stop_event in stop_states:
                """ Stopped correctly """
                return get_time_diff_seconds(self.time_resume, self.time_stop)
            elif self.stop_event in anomaly_states:
                if self.time_stop:
                    return get_time_diff_seconds(self.time_resume, self.time_stop)
                
                """ Stopped with guess """
                next_block = self.next

                while next_block:
                    if next_block.time_stop or next_block.app_name != self.app_name:
                        break
                    
                    next_block = next_block.next
                
                if not next_block:
                    if self.time_pause:
                        return get_time_diff_seconds(self.time_resume, self.time_pause)
                else:
                    if next_block.app_name == self.app_name:
                        #print("next block stop")
                        self.time_stop = next_block.time_stop
                        self.stop_event = NSI
                    else:
                        #print("no stop, next block:%s,%s,%s,%s,%s" % (next_block.app_name, next_block.time_resume, next_block.resume_event, next_block.time_pause, next_block.pause_event))
                        self.time_stop = next_block.time_resume
                        self.stop_event = MST
                    
                    #print("debug", self.app_name, self.time_stop)
                    if self.time_stop:
                        # in case the next block has no resume_time.
                        return get_time_diff_seconds(self.time_resume, self.time_stop)
            else:
                """ 
                Not Stopped: search for the block list for the next Stopped block of the same App (consecutive) or next block of a different App.
                """
                #print("warning: blocks not stopped: %s,%s,%s,%s,%s,%s,%s" % (self.app_name,self.time_resume, self.resume_event, self.time_pause, self.pause_event, self.time_stop, self.stop_event))
                if self.time_resume and self.time_pause:
                    return get_time_diff_seconds(self.time_resume, self.time_pause)
        
        #print("resume/stop time missing:", self.time_resume, self.time_pause, self.time_stop)

        # resume/stop time missing, return 0
        return 0
    
    def __eq__(self, other):
        if not isinstance(other, ActivityBlock):
            return NotImplemented
        return str(self) == str(other)
        
class ScreenTimeLogs:
    def __init__(self, filename, proximity_interval, outfile, logfile, struct_logic=True):
        self.proximity_interval = proximity_interval

        self.outfile = outfile
        self.logfile = logfile
        self.struct_logic = struct_logic

        self.df = pd.read_csv(filename)

        # keep track of all logs
        self.logs = []


        self.queues_resume = {}
        self.queue_resumed = deque()

        self.queues_pause = {}
        self.queue_paused = deque()

        self.queues_stop = {}
        self.queue_stopped = deque()

        self.debug_blocks = []

        self.num_resume = 0
        self.num_pause = 0
        self.num_stop = 0

    def in_proximity(self, t1_str, t2_str):
        t1 = datetime.fromisoformat(t1_str)
        t2 = datetime.fromisoformat(t2_str)

        d = t2 - t1
        s = d.total_seconds()

        if abs(s) < self.proximity_interval:
            return True
        
        return False

    def left_behind(self, app_name):
        """True when the app has an activity that is Paused and not yet Stopped. A Stopped then belongs to that
        activity, however late it comes: an activity is always Paused before it is Stopped (David, 10-15: with a
        complete log this reading makes the whole log "more logical").
        - Hand-over: Paused(A1) -> Resumed(A2) -> Stopped(A1). Games draw their first frame slowly, so the Stopped
          can come seconds later: Aizhong's Delta Force (com.tencent.tmgp.dfm) 2026-10-11, Stopped(Splash) 2.1 s
          after Resumed(GameActivity); read as a kill, its 48 min were lost (pattern C7).
        - Small window or Recents: the app stays Paused with no Stopped until the window or card is closed.
        A real kill (force stop, crash) of the activity in front logs Stopped with no Paused, and the next app
        Resumed in the same second (test phone 10-15, pattern C8): that is the case left for AppKilled."""
        q = self.queues_pause.get(app_name)
        if not q or q[-1].is_stopped() or not q[-1].time_pause:
            return False
        # Screen off, shutdown and boot stop every activity (test phone 10-15): one still waiting from before them
        # lost its Stopped, and is no longer a candidate.
        return self.last_reset is None or q[-1].time_pause > self.last_reset

    def reconstruct_blocks(self):
        self.num_resume = 0
        self.num_pause = 0
        self.num_stop = 0

        prev_block = None
        curr_block = None
        self.last_reset = None      # time of the last screen-off, shutdown or boot (see left_behind)

        #for i in range(len(self.logs)):
        for i in range(0, len(self.df)):

            log = self.df.iloc[i].to_list()

            log[APP_LABEL] = log[APP_LABEL].replace(',',' ') # the comma will skew up results

            app_name = log[APP_NAME]
            app_label = log[APP_LABEL]
            #print(i, app_name)
            interaction_type = log[INT_TYPE]
            if interaction_type in reset_states or interaction_type in reboot_states:
                self.last_reset = log[EVENT_TS]

            if interaction_type in foreground_states:
                self.num_resume += 1
                # Here we should create a new 'resumed' block upon 'Activity Resumed' or 'Move to Foreground"
                # 
                # Note: there might be multiple consecutive 'resumed' blocks.
                alb = ActivityBlock(app_name=app_name, time_resume=log[EVENT_TS], resume_event=interaction_type, app_label=app_label, log_id=i)
                
                if prev_block:
                    prev_block.next = alb
                prev_block = alb
                
                if not app_name in self.queues_resume:
                    self.queues_resume[app_name] = deque()
                    self.queues_pause[app_name] = deque()
                    self.queues_stop[app_name] = deque()

                self.queues_resume[app_name].append(alb)

            elif interaction_type in background_states:
                self.num_pause += 1
                """
                Three cases:
                1) There are multiple preceding 'resumed' blocks:
                2) There is only a single preceding 'resumed block: 
                   -- match this 'paused' to the preceding 'resumed' block;
                3) There is no preceding 'resumed' block: 
                   -- create a block without 'time_resume'.
                """
                if not app_name in self.queues_resume:
                    """ The 'Activity Paused' appear first in the log file"""
                    self.queues_resume[app_name] = deque()
                    self.queues_pause[app_name] = deque()
                    self.queues_stop[app_name] = deque()

                curr_num_resumed = len(self.queues_resume[app_name])

                if curr_num_resumed >= 2:
                    """ 
                    Now, it's time to decide which 'resumed' this 'paused' should match to.
                    """
                    b2 = self.queues_resume[app_name][-2]
                    b1 = self.queues_resume[app_name][-1]

                    target_block = None
                    # by default, match the 'paused' to the latest 'resumed'
                    if b2.next == b1 and self.in_proximity(b1.time_resume, log[EVENT_TS]): 
                        # When the 'paused' is within the proximity of the preceding 'resumed', 
                        # then match the 'paused' to the previous 'resumed'.
                        target_block = b2
                        target_block.pause_event = MPB
                    else:
                        target_block = b1
                        target_block.pause_event = MCB

                    target_block.time_pause = log[EVENT_TS]
                    
                    # stop all 'resumed' blocks preceding the current 'resumed' block
                    while len(self.queues_resume[app_name]) > 0:
                        alb = self.queues_resume[app_name].popleft()

                        if alb == target_block:
                            break
                        
                        alb.pause_event = NPI #"nextpausedinference"
                        
                        # put the block into 'queue_paused'
                        self.queues_pause[app_name].append(alb)

                        # put this block into debug_blocks for future investigation
                        self.debug_blocks.append(alb)

                    # put the target block into 'queue_paused'
                    self.queues_pause[app_name].append(target_block)    

                elif curr_num_resumed == 1:
                    alb = self.queues_resume[app_name].popleft()

                    alb.time_pause = log[EVENT_TS]
                    alb.pause_event = interaction_type

                    self.queues_pause[app_name].append(alb)
                else:
                    # curr_num_resumed == 0
                    # "MAR - missing activity resumed"
                    alb = ActivityBlock(app_name=app_name, resume_event=MAR, time_pause=log[EVENT_TS],pause_event=interaction_type, app_label=app_label, log_id=i)
                    
                    if prev_block:
                        prev_block.next = alb
                    prev_block = alb

                    self.queues_pause[app_name].append(alb)
                    self.debug_blocks.append(alb)

            elif interaction_type in stop_states:
                self.num_stop += 1
                """
                Normally, the 'Stopped' event should immediately follow the 'Paused' event, indicating the App goes to invisible.

                However, there is a common case that this Activity invokes another Activity before it goes to invisible, and
                the event sequence becomes: 
                ... Paused (A1) -> Resumed (A2) -> Stopped (A1) ...
                or
                ... Paused (A1) -> Resumed (A2) -> Paused (A2) -> Resumed (A3) -> Stopped (A1) -> Stopped (A2) ...

                Therefore, we consider two cases:
                1) If the preceding block is not 'resumed', then all previous blocks should be -> stopped.
                2) If the preceding block is 'resumed', find the 1st block that needs 'time_stop'.
                   -- if the 'stopped' is within 1s proximity of the preceding 'resumed', then match this 'stopped' to previous blocks (that need 'stopped');
                   -- else, match the 'stopped' to this 'resumed' (App gets killed).
                
                """
                if not app_name in self.queues_resume:
                    self.queues_resume[app_name] = deque()
                    self.queues_pause[app_name] = deque()
                    self.queues_stop[app_name] = deque()
                
                if len(self.queues_resume[app_name]) <= 0:
                    # all blocks in 'queue_paused' should be stopped
                    if len(self.queues_pause[app_name]) <= 0:
                        # single 'Stopped' event, this is an unusual case.
                        alb = ActivityBlock(app_name=app_name, time_stop=log[EVENT_TS],stop_event=interaction_type, log_id=i)

                        if prev_block:
                            prev_block.next = alb
                        prev_block = alb

                        self.queues_stop[app_name].append(alb)

                        self.debug_blocks.append(alb)
                    else:

                        curr_block = self.queues_pause[app_name][-1]
                        curr_block.time_stop = log[EVENT_TS]
                        curr_block.stop_event = interaction_type

                        """
                        Remember this is for all activities in the same App. Should this 'Stopped' stop all the  preceding 'Paused' events?
                        """
                        
                        while len(self.queues_pause[app_name]) > 0:
                            alb = self.queues_pause[app_name].popleft()

                            if alb == curr_block:
                                break
                            
                            if not alb.is_stopped():
                                # 'NSI - nextblockstoppedinference' 
                                alb.stop_event = NSI
                            
                            # put it into the 'queue_stopped'
                            self.queues_stop[app_name].append(alb)
                        
                        #self.queues_pause[app_name].pop()
                        self.queues_stop[app_name].append(curr_block)
                else:
                    b1 = self.queues_resume[app_name][-1]
                    if self.left_behind(app_name) or self.in_proximity(b1.time_resume, log[EVENT_TS]):
                        """
                        Find the latest block that needs a 'Stopped'.
                        """
                        curr_block = None
                        
                        if len(self.queues_pause[app_name]) > 0:
                            curr_block = self.queues_pause[app_name].pop()

                            """
                            curr_block = self.queues_pause[app_name][-1]
                            
                            while len(self.queues_pause[app_name]) > 0:
                                alb = self.queues_pause[app_name].popleft()
                                if alb == curr_block:
                                    break
                            
                                if not alb.is_stopped():
                                    alb.stop_event = NSI

                                self.queues_stop[app_name].append(alb)
                            """
                            #self.queues_pause[app_name].pop()
                        else:
                            curr_block = self.queues_resume[app_name].popleft()
                        
                        
                        curr_block.time_stop = log[EVENT_TS]
                        curr_block.stop_event = interaction_type
                        
                        self.queues_stop[app_name].append(curr_block)
                    else:
                        # App gets killed, all activities should be stopped.
                        if len(self.queues_resume[app_name]) > 0:
                            alb = self.queues_resume[app_name][-1]
                        elif len(self.queues_pause[app_name]) > 0:
                            alb = self.queues_pause[app_name][-1]
                        else:
                            alb = None
                            #self.debug_blocks.append(log)

                        if alb:
                            alb.time_stop = log[EVENT_TS]
                            alb.stop_event = AKD # 'AKD - app killed'
                        
                        while len(self.queues_pause[app_name]) > 0:
                            alb = self.queues_pause[app_name].popleft()
                            
                            if not alb.is_stopped():
                                alb.stop_event = AKD

                            self.queues_stop[app_name].append(alb)

                        while len(self.queues_resume[app_name]) > 0:
                            alb = self.queues_resume[app_name].popleft()
                            alb.stop_event = AKD

                            self.queues_stop[app_name].append(alb)

            elif interaction_type in reboot_states:
                """
                All preceding non-stopped blocks should be changed -> "stopped".
                
                But, we need to figure out the time for the 'stopped'.
                
                One thing is certain: the previous block's stop time is 'now'.
                """
                
                if curr_block and (not curr_block.time_stop):
                    curr_block.stop_event = SSD
                    curr_block.time_stop = log[EVENT_TS]

                #if interaction_type == 'Gap Identified':
                #    print("prev_block:", str(prev_block))
                #    print("debug ->", app_name, app_label, interaction_type)

                for app_name in self.queues_pause:
                    while len(self.queues_pause[app_name]) > 0:
                        # Assume it's in the multi-view scenario: The app paused but didn't stop.
                        alb = self.queues_pause[app_name].popleft()
                        alb.stop_event = SSD # 'SSD - system shut down'

                        self.queues_stop[app_name].append(alb)

                for app_name in self.queues_resume:
                    while len(self.queues_resume[app_name]) > 0:
                        # This is a 'troublesome' scenario where the App resumed but never pause/stop.
                        alb = self.queues_resume[app_name].popleft()
                        alb.stop_event = SSD # SSD - system shut down

                        self.queues_stop[app_name].append(alb)

            else:
                # unknown interaction types
                #print("** unknown interaction type:", interaction_type)
                pass

    def dump_stats(self):
        print("++ stats for app: %s" % self.app_name)
        print("resume: %d" % self.num_resume)
        print(" pause: %d" % self.num_pause)
        print("  stop: %d" % self.num_stop)
        print(" other: %d" % (len(self.logs) - self.num_resume - self.num_pause - self.num_stop))
        print(" total: %d" % len(self.logs))
              
    def dump_logs(self):
        for log in self.logs:
            print(','.join(log))

    def blocks2csv(self):
        def clean(value):
            if value is None:
                return value
            return str(value).replace("\r", " ").replace("\n", " ")

        with open(self.outfile, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                "app_package_name",
                "resume_time",
                "resume_event",
                "pause_time",
                "pause_event",
                "stop_time",
                "stop_event",
                "app_label",
                "duration",
            ])

            for queue in (self.queues_resume, self.queues_pause, self.queues_stop):
                for app_name in queue:
                    for b in queue[app_name]:
                        writer.writerow([
                            clean(b.app_name),
                            clean(b.time_resume),
                            clean(b.resume_event),
                            clean(b.time_pause),
                            clean(b.pause_event),
                            clean(b.time_stop),
                            clean(b.stop_event),
                            clean(b.app_label),
                            f"{b.duration(self.struct_logic):.3f}",
                        ])

    def debug2csv(self):
        f = open(self.logfile, 'w')
        for b in self.debug_blocks:
            f.write("%s\n" % b)
        f.close()

    def dump_all_blocks(self):
        print("resumed:")
        for b in self.queue_resumed:
            print("%s,%s,%.3f" % (self.app_name, b, b.duration()))

        print("paused:")
        for b in self.queue_paused:
            print("%s,%s,%.3f" % (self.app_name, b, b.duration()))

        print("stopped:")
        for b in self.queue_stopped:
            print("%s,%s,%.3f" % (self.app_name, b, b.duration()))


    def dump_unstopped_blocks(self):
        print("** UnStopped blocks: %d" % (len(self.blocks) - self.num_stopped_blocks))
        for i in range(self.num_stopped_blocks, len(self.blocks)):
            print(i, self.blocks[i])


    def dump_summary(self):
        n = len(self.logs)
        ts_start = self.logs[0][EVENT_TS]
        ts_end = self.logs[-1][EVENT_TS]

        print("%d,\t%s, %s, %s" % (n, ts_start, ts_end, self.app_name))

def get_time_diff_seconds(t1_str, t2_str):
        t1 = datetime.fromisoformat(t1_str)
        t2 = datetime.fromisoformat(t2_str)

        d = t2 - t1
        return d.total_seconds()


def load_chronicle_log(filename):
    df = pd.read_csv(filename)
    return df


import os

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage:", sys.argv[0], "<chronicle_log_file><n_seconds><struct_logic=Y/N>")
        sys.exit(1)

    filename = sys.argv[1]
    seconds = int(sys.argv[2])
    
    struct_logic = False 
    
    if sys.argv[3].capitalize() == 'Y':
        struct_logic = True

    dir_name = os.path.dirname(filename)
    file_name = os.path.basename(filename)

    tokens = file_name.split('.')
    # the clean log (offscreen_chains) keeps the usual output names
    tokens[0] = tokens[0][:-len('_clean')] if tokens[0].endswith('_clean') else tokens[0]

    logfile = "%s/%s_log_one.csv" % (dir_name, tokens[0])
    outfile = "%s/%s_act_one.csv" % (dir_name, tokens[0])

    stl = ScreenTimeLogs(filename, seconds, outfile, logfile, struct_logic=struct_logic)

    #df = load_chronicle_log(filename)
    #print(df)
    #print(df['app_package_name'].value_counts())
    stl.reconstruct_blocks()
    stl.blocks2csv()
    stl.debug2csv()


    #for e in sorted_list:
    #    e[1].dump_summary()
    
