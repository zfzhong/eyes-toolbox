"""Compatibility wrapper for eyeslib.preprocess.pre_process."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("eyeslib.preprocess.pre_process", run_name="__main__")
else:
    from eyeslib.preprocess.pre_process import *  # noqa: F401,F403
