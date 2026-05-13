"""Compatibility wrapper for eyeslib.runners.run_parser4."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("eyeslib.runners.run_parser4", run_name="__main__")
else:
    from eyeslib.runners.run_parser4 import *  # noqa: F401,F403
