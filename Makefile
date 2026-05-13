PYTHON ?= python

preprocess:
	$(PYTHON) -m eyeslib.preprocess.pre_process $(dir)

uniq:	preprocess
	$(PYTHON) -m eyeslib.preprocess.uniq $(dir)

reorder: uniq
	$(PYTHON) -m eyeslib.preprocess.reorder $(dir)

gap:	reorder
	$(PYTHON) -m eyeslib.runners.run_gap_segments $(dir)

shutdown:	gap
	$(PYTHON) -m eyeslib.runners.run_shutdown_segments $(dir)

idle:	shutdown
	$(PYTHON) -m eyeslib.runners.run_idle_segments $(dir)

blocks:	idle
	$(PYTHON) -m eyeslib.runners.run_all_blocks $(dir)

pickups:	
	$(PYTHON) -m eyeslib.runners.run_all_pickups $(dir) 5 5

pickupstz:	pickups
	$(PYTHON) -m eyeslib.runners.run_tz_columns_for_pickups $(dir)

parser:	blocks
	$(PYTHON) -m eyeslib.runners.run_parser4 $(dir) Y

app:	parser
	$(PYTHON) -m eyeslib.runners.run_app_level $(dir)

nest:	app	
	$(PYTHON) -m eyeslib.runners.run_secondary_nest $(dir)

merge:	nest
	$(PYTHON) -m eyeslib.runners.run_merge_app_status $(dir)

fau:	merge
	$(PYTHON) -m eyeslib.runners.run_fau_screen_time $(dir)

allevents:
	$(PYTHON) -m eyeslib.runners.run_all_events $(dir)

eventstz:	allevents
	$(PYTHON) -m eyeslib.runners.run_tz_columns_for_events $(dir)

visual:	fau
	$(PYTHON) -m eyeslib.usage.visualize_app_usage $(dir)

gui:
	$(PYTHON) -m eyeslib.gui.app

all: visual pickups

clean: 
	rm -rf $(dir)/processed
