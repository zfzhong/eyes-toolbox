"""Compatibility wrapper for eyeslib.preprocess.reorder."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("eyeslib.preprocess.reorder", run_name="__main__")
else:
    from eyeslib.preprocess.reorder import *  # noqa: F401,F403
