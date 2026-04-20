"""
Wrapper for pip that fixes a known crash on restricted Windows machines.
Patches the platformdirs registry lookup that fails when CSIDL_COMMON_APPDATA
is inaccessible due to group policy.
See: https://github.com/pypa/pip/issues/13708
"""
import os
import sys

def _patch_pip():
    if os.name != 'nt':
        return
    try:
        import pip._vendor.platformdirs.windows as w
        if not hasattr(w, 'get_win_folder_from_registry'):
            return
        if not hasattr(w, 'get_win_folder_from_env_vars'):
            return

        _orig = w.get_win_folder_from_registry
        _env_fallback = w.get_win_folder_from_env_vars

        def safe_get_win_folder(csidl_name):
            try:
                return _orig(csidl_name)
            except (FileNotFoundError, OSError):
                return _env_fallback(csidl_name)

        w.get_win_folder_from_registry = safe_get_win_folder
        if hasattr(w, 'get_win_folder'):
            w.get_win_folder = safe_get_win_folder
    except Exception:
        pass

_patch_pip()

if __name__ == '__main__':
    from pip._internal.cli.main import main
    sys.exit(main(sys.argv[1:]))
