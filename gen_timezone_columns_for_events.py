"""Compatibility wrapper for eyeslib.exports.gen_timezone_columns_for_events."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("eyeslib.exports.gen_timezone_columns_for_events", run_name="__main__")
else:
    from eyeslib.exports.gen_timezone_columns_for_events import *  # noqa: F401,F403
