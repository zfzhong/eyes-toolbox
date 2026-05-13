"""Compatibility wrapper for eyeslib.preprocess.uniq."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("eyeslib.preprocess.uniq", run_name="__main__")
else:
    from eyeslib.preprocess.uniq import *  # noqa: F401,F403
