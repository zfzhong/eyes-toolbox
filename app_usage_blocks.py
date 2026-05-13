"""Compatibility wrapper for eyeslib.usage.app_usage_blocks."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("eyeslib.usage.app_usage_blocks", run_name="__main__")
else:
    from eyeslib.usage.app_usage_blocks import *  # noqa: F401,F403
