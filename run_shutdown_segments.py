"""Compatibility wrapper for eyeslib.runners.run_shutdown_segments."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("eyeslib.runners.run_shutdown_segments", run_name="__main__")
else:
    from eyeslib.runners.run_shutdown_segments import *  # noqa: F401,F403
