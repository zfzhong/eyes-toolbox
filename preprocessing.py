"""Compatibility wrapper for eyeslib.preprocess.preprocessing."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("eyeslib.preprocess.preprocessing", run_name="__main__")
else:
    from eyeslib.preprocess.preprocessing import *  # noqa: F401,F403
