"""Compatibility wrapper for eyeslib.exports.gen_all_events."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("eyeslib.exports.gen_all_events", run_name="__main__")
else:
    from eyeslib.exports.gen_all_events import *  # noqa: F401,F403
