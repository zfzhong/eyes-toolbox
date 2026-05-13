"""Compatibility wrapper for eyeslib.gui.app."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("eyeslib.gui.app", run_name="__main__")
else:
    from eyeslib.gui.app import *  # noqa: F401,F403
