"""Compatibility wrapper for eyeslib.runners.run_secondary_nest."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("eyeslib.runners.run_secondary_nest", run_name="__main__")
else:
    from eyeslib.runners.run_secondary_nest import *  # noqa: F401,F403
