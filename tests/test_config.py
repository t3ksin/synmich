"""Config loading merges defaults."""

import yaml

from synmich.config import DEFAULT_CONFIG, load_config, validate_config


def test_load_config_missing_file_returns_empty(tmp_path):
    assert load_config(tmp_path / "nope.yaml") == {}


def test_load_config_merges_defaults(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "synology": {"url": "http://nas:5000"},
                "immich": {"url": "http://immich:2283"},
                "users": [
                    {
                        "name": "a",
                        "syno_username": "a",
                        "syno_password": "x",
                        "immich_api_key": "k",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg["synology"]["url"] == "http://nas:5000"
    assert cfg["execution"]["workers"] == DEFAULT_CONFIG["execution"]["workers"]
    assert cfg["migration"]["albums_mode"] == "all"
    assert cfg["filters"]["include_videos"] is True
    assert validate_config(cfg) == []


def test_validate_rejects_unknown_shared_mode():
    data = {
        "synology": {"url": "http://n"},
        "immich": {"url": "http://i"},
        "users": [
            {
                "name": "a",
                "syno_username": "a",
                "syno_password": "x",
                "immich_api_key": "k",
            }
        ],
        "migration": {"shared_albums_mode": "nope"},
    }
    errs = validate_config(data)
    assert any("shared_albums_mode" in e for e in errs)
