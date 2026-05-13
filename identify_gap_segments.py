"""Compatibility wrapper for eyeslib.segments.identify_gap_segments."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("eyeslib.segments.identify_gap_segments", run_name="__main__")
else:
    from eyeslib.segments.identify_gap_segments import *  # noqa: F401,F403
