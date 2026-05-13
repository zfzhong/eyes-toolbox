"""Compatibility wrapper for eyeslib.usage.merge_app_status."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("eyeslib.usage.merge_app_status", run_name="__main__")
else:
    from eyeslib.usage.merge_app_status import *  # noqa: F401,F403
