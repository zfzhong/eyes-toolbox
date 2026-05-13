"""Compatibility wrapper for eyeslib.core.blocks_from_csv."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("eyeslib.core.blocks_from_csv", run_name="__main__")
else:
    from eyeslib.core.blocks_from_csv import *  # noqa: F401,F403
