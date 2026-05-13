"""Compatibility wrapper for eyeslib.core.plot_all_blocks."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("eyeslib.core.plot_all_blocks", run_name="__main__")
else:
    from eyeslib.core.plot_all_blocks import *  # noqa: F401,F403
