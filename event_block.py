"""Compatibility wrapper for eyeslib.core.event_block."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("eyeslib.core.event_block", run_name="__main__")
else:
    from eyeslib.core.event_block import *  # noqa: F401,F403
