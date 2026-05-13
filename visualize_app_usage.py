"""Compatibility wrapper for eyeslib.usage.visualize_app_usage."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("eyeslib.usage.visualize_app_usage", run_name="__main__")
else:
    from eyeslib.usage.visualize_app_usage import *  # noqa: F401,F403
