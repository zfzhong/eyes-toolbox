"""Compatibility wrapper for eyeslib.segments.identify_shutdown_or_idle_segments."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("eyeslib.segments.identify_shutdown_or_idle_segments", run_name="__main__")
else:
    from eyeslib.segments.identify_shutdown_or_idle_segments import *  # noqa: F401,F403
