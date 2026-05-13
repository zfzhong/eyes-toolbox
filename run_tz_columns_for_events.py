"""Compatibility wrapper for eyeslib.runners.run_tz_columns_for_events."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("eyeslib.runners.run_tz_columns_for_events", run_name="__main__")
else:
    from eyeslib.runners.run_tz_columns_for_events import *  # noqa: F401,F403
