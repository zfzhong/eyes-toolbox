"""Compatibility wrapper for eyeslib.exports.gen_pickups."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("eyeslib.exports.gen_pickups", run_name="__main__")
else:
    from eyeslib.exports.gen_pickups import *  # noqa: F401,F403
