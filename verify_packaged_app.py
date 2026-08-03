from __future__ import annotations

import os
import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: verify_packaged_app.py <bundled-internal-directory>", file=sys.stderr)
        return 2

    bundled_directory = Path(sys.argv[1]).resolve()
    bundled_app = bundled_directory / "app.py"
    if not bundled_app.is_file():
        print(f"Bundled app was not found: {bundled_app}", file=sys.stderr)
        return 2

    project_root = Path(__file__).resolve().parent
    isolated_paths: list[str] = [str(bundled_directory)]
    for entry in sys.path:
        try:
            resolved_entry = Path(entry or ".").resolve()
        except OSError:
            isolated_paths.append(entry)
            continue
        if resolved_entry != project_root and resolved_entry != bundled_directory:
            isolated_paths.append(entry)

    sys.path[:] = isolated_paths
    os.chdir(bundled_directory)

    app_test = AppTest.from_file(str(bundled_app))
    app_test.run(timeout=45)
    if app_test.exception:
        for exception in app_test.exception:
            print(str(exception.value), file=sys.stderr)
        return 1

    print("Packaged Streamlit session completed without an application exception.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())