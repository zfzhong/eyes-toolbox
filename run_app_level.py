"""Compatibility wrapper for eyeslib.runners.run_app_level."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("eyeslib.runners.run_app_level", run_name="__main__")
else:
    from eyeslib.runners.run_app_level import *  # noqa: F401,F403
