"""Compatibility wrapper for eyeslib.runners.run_gap_segments."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("eyeslib.runners.run_gap_segments", run_name="__main__")
else:
    from eyeslib.runners.run_gap_segments import *  # noqa: F401,F403
