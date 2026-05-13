"""Compatibility wrapper for eyeslib.exports.gen_timezone_columns."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("eyeslib.exports.gen_timezone_columns", run_name="__main__")
else:
    from eyeslib.exports.gen_timezone_columns import *  # noqa: F401,F403
