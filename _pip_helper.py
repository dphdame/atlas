"""
Wrapper for pip that fixes a known crash on restricted Windows machines.

Patches the platformdirs registry lookup that fails when CSIDL_COMMON_APPDATA
is inaccessible due to group policy, falling back to environment variables.
See: https://github.com/pypa/pip/issues/13708

Usage (from the launcher): python _pip_helper.py install -r requirements.txt
"""

import os
import sys


def _patch_pip() -> None:
    if os.name != "nt":
        return
    try:
        import pip._vendor.platformdirs.windows as win_dirs
    except ImportError:
        return
    if not hasattr(win_dirs, "get_win_folder_from_registry"):
        return
    if not hasattr(win_dirs, "get_win_folder_from_env_vars"):
        return

    original = win_dirs.get_win_folder_from_registry
    env_fallback = win_dirs.get_win_folder_from_env_vars

    def safe_get_win_folder(csidl_name):
        try:
            return original(csidl_name)
        except OSError:
            return env_fallback(csidl_name)

    win_dirs.get_win_folder_from_registry = safe_get_win_folder
    if hasattr(win_dirs, "get_win_folder"):
        win_dirs.get_win_folder = safe_get_win_folder


_patch_pip()

if __name__ == "__main__":
    from pip._internal.cli.main import main

    sys.exit(main(sys.argv[1:]))
