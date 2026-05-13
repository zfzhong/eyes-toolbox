"""Compatibility wrapper for eyeslib.usage.chronicle_app_log_parser4."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("eyeslib.usage.chronicle_app_log_parser4", run_name="__main__")
else:
    from eyeslib.usage.chronicle_app_log_parser4 import *  # noqa: F401,F403
