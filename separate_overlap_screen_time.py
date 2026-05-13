"""Compatibility wrapper for eyeslib.usage.separate_overlap_screen_time."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("eyeslib.usage.separate_overlap_screen_time", run_name="__main__")
else:
    from eyeslib.usage.separate_overlap_screen_time import *  # noqa: F401,F403
