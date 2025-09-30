import sys
from pathlib import Path

import json
import builtins


# Ensure we can import the editable package without installation
PROJECT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from qa_crawler.search import (  # noqa: E402
    tokenize_query,
    exact_match_urls,
    top_similar_combinations,
    main as search_main,
)


def make_block_map():
    return {
        "hash1": {"class_names": ["hero", "centered"], "urls": ["https://a.example/hero1"]},
        "hash2": {"class_names": ["hero", "left"], "urls": ["https://a.example/hero2"]},
        "hash3": {"class_names": ["text", "centered"], "urls": ["https://a.example/text1"]},
        "hash4": {"class_names": ["grid", "center"], "urls": ["https://a.example/grid1"]},
        "hash5": {"class_names": ["page", "banner"], "urls": ["https://a.example/banner1"]},
    }


def test_exact_match_urls():
    bm = make_block_map()
    tokens = tokenize_query("hero centered")
    urls = exact_match_urls(bm, tokens)
    assert "https://a.example/hero1" in urls
    assert all("centered" in bm[h]["class_names"] for h in bm if any(u in urls for u in bm[h].get("urls", [])))


def test_top_similar_combinations_scores_sorted():
    bm = make_block_map()
    combos = top_similar_combinations(bm, "centered", top_k=5)
    # Each combo is (combo_str, score, hash)
    assert 1 <= len(combos) <= 5
    # Scores non-increasing
    scores = [s for _c, s, _h in combos]
    assert scores == sorted(scores, reverse=True)
    # At least one includes 'centered'
    assert any("centered" in c for c, _s, _h in combos)


def test_cli_with_explicit_path(tmp_path, capsys, monkeypatch):
    # Write a temporary block_map.json
    bm = make_block_map()
    bm_path = tmp_path / "block_map.json"
    bm_path.write_text(json.dumps(bm), encoding="utf-8")

    # Invoke CLI main() by patching argv
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    argv = [
        "search_block_map.py",
        "hero centered",
        "--path",
        str(bm_path),
        "--limit",
        "5",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    rc = search_main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "Exact match (all keywords):" in out
    assert "https://a.example/hero1" in out
    assert "Top 5 similar class name combinations" in out
