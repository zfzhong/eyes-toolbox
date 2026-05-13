"""Compatibility wrapper for eyeslib.runners.run_tz_columns_for_pickups."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("eyeslib.runners.run_tz_columns_for_pickups", run_name="__main__")
else:
    from eyeslib.runners.run_tz_columns_for_pickups import *  # noqa: F401,F403
