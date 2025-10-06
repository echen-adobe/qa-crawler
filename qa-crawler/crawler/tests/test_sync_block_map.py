import sys
from pathlib import Path
import json


PROJECT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def test_sync_writes_valid_json(tmp_path, monkeypatch):
    # Create a repo-like layout under tmp_path
    repo_root = tmp_path / "qa-crawler"
    data_qa = repo_root / "data" / "qa"
    data_qa.mkdir(parents=True, exist_ok=True)

    data = {"abc": {"class_names": ["foo"], "urls": ["u1"]}}
    src_path = data_qa / "block_map.json"
    src_path.write_text(json.dumps(data), encoding="utf-8")

    script_dir = repo_root / "scripts"
    script_dir.mkdir(parents=True, exist_ok=True)

    # Copy the actual script into this tmp repo so import-relative paths resolve
    from shutil import copyfile
    original_script = PROJECT_DIR / "scripts" / "sync_block_map.py"
    target_script = script_dir / "sync_block_map.py"
    copyfile(original_script, target_script)

    # Run the script via import and calling main
    sys.path.insert(0, str(repo_root))
    import importlib.util
    spec = importlib.util.spec_from_file_location("sync_block_map", str(target_script))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)  # type: ignore

    # Call main with today date
    from datetime import date
    d = date.today().isoformat()
    sys_argv = ["sync_block_map.py", "--root", str(repo_root), "--date", d]

    # Monkeypatch argv
    old_argv = sys.argv
    sys.argv = sys_argv
    try:
        rc = mod.main()
    finally:
        sys.argv = old_argv
    assert rc == 0

    out_file = repo_root / "output" / d / "block_map.json"
    assert out_file.exists()
    loaded = json.loads(out_file.read_text(encoding="utf-8"))
    assert loaded == data


def test_sync_rejects_invalid_json(tmp_path, monkeypatch):
    repo_root = tmp_path / "qa-crawler"
    data_qa = repo_root / "data" / "qa"
    data_qa.mkdir(parents=True, exist_ok=True)

    # Write invalid JSON
    src_path = data_qa / "block_map.json"
    src_path.write_text("{"""not-json"""}", encoding="utf-8")

    script_dir = repo_root / "scripts"
    script_dir.mkdir(parents=True, exist_ok=True)

    from shutil import copyfile
    original_script = PROJECT_DIR / "scripts" / "sync_block_map.py"
    target_script = script_dir / "sync_block_map.py"
    copyfile(original_script, target_script)

    import importlib.util
    spec = importlib.util.spec_from_file_location("sync_block_map", str(target_script))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)  # type: ignore

    from datetime import date
    d = date.today().isoformat()
    sys_argv = ["sync_block_map.py", "--root", str(repo_root), "--date", d]
    old_argv = sys.argv
    sys.argv = sys_argv
    try:
        rc = mod.main()
    finally:
        sys.argv = old_argv
    assert rc != 0
