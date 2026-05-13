"""Compatibility wrapper for eyeslib.segments.build_idle_blocks."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("eyeslib.segments.build_idle_blocks", run_name="__main__")
else:
    from eyeslib.segments.build_idle_blocks import *  # noqa: F401,F403
