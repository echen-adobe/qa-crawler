#!/usr/bin/env python3
import os
import sys


def main() -> int:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src_path = os.path.join(repo_root, "src")
    existing = os.environ.get("PYTHONPATH", "")
    os.environ["PYTHONPATH"] = f"{src_path}:{existing}" if existing else src_path

    venv_python = os.path.join(repo_root, "venv", "bin", "python3")
    python_exe = venv_python if os.path.exists(venv_python) else sys.executable

    # Re-exec as module qa_crawler.cli.search preserving args
    argv = [python_exe, "-m", "qa_crawler.cli.search", *sys.argv[1:]]

    # Use os.execvpe to inherit env and replace current process
    os.execvpe(argv[0], argv, os.environ)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

