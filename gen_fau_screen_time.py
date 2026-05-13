"""Compatibility wrapper for eyeslib.exports.gen_fau_screen_time."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("eyeslib.exports.gen_fau_screen_time", run_name="__main__")
else:
    from eyeslib.exports.gen_fau_screen_time import *  # noqa: F401,F403
