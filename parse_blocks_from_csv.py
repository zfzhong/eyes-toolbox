"""Compatibility wrapper for eyeslib.segments.parse_blocks_from_csv."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("eyeslib.segments.parse_blocks_from_csv", run_name="__main__")
else:
    from eyeslib.segments.parse_blocks_from_csv import *  # noqa: F401,F403
