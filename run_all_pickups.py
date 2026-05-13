"""Compatibility wrapper for eyeslib.runners.run_all_pickups."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("eyeslib.runners.run_all_pickups", run_name="__main__")
else:
    from eyeslib.runners.run_all_pickups import *  # noqa: F401,F403
