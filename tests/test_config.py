import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import DEFAULTS, load_config


def test_load_config_returns_defaults_when_file_missing(tmp_path):
    path = tmp_path / "config.json"
    cfg = load_config(str(path))
    assert cfg == DEFAULTS
    # Le fichier est créé pour servir de point de départ modifiable.
    assert os.path.exists(path)
    assert json.load(open(path, encoding="utf-8"))["blacklist_classes"] == [
        "cell phone"
    ]


def test_load_config_merges_user_overrides(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"blacklist_classes": ["cell phone", "book"], "analysis_fps": 5}),
        encoding="utf-8",
    )
    cfg = load_config(str(path))
    assert cfg["blacklist_classes"] == ["cell phone", "book"]
    assert cfg["analysis_fps"] == 5
    # Les clés non surchargées gardent leur valeur par défaut.
    assert cfg["frames_to_change_state"] == DEFAULTS["frames_to_change_state"]


def test_load_config_ignores_unknown_and_broken_keys(tmp_path):
    path = tmp_path / "not_json.json"
    path.write_text("{invalid json", encoding="utf-8")
    assert load_config(str(path)) == DEFAULTS
