"""Config-hashed checkpoints."""

from synmich.core.checkpoint import (
    Checkpoint,
    _config_hash,
    get_checkpoint_path_for_config,
)


def test_config_hash_stable_for_same_axes():
    cfg = {
        "synology": {"url": "http://nas:5000/"},
        "immich": {"url": "http://immich:2283"},
        "users": [{"name": "b"}, {"name": "a"}],
    }
    cfg2 = {
        "synology": {"url": "http://nas:5000"},
        "immich": {"url": "http://immich:2283"},
        "users": [{"name": "a"}, {"name": "b"}],
    }
    assert _config_hash(cfg) == _config_hash(cfg2)


def test_config_hash_changes_when_user_added():
    cfg = {
        "synology": {"url": "http://nas:5000"},
        "immich": {"url": "http://immich:2283"},
        "users": [{"name": "a"}],
    }
    cfg2 = {**cfg, "users": [{"name": "a"}, {"name": "b"}]}
    assert _config_hash(cfg) != _config_hash(cfg2)


def test_checkpoint_path_uses_hash(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg = {
        "synology": {"url": "http://nas:5000"},
        "immich": {"url": "http://immich:2283"},
        "users": [{"name": "a"}],
    }
    path = get_checkpoint_path_for_config(cfg)
    assert path.parent.name == "checkpoints"
    assert path.suffix == ".json"
    assert _config_hash(cfg) in path.name


def test_mark_uploaded_accepts_was_duplicate(tmp_path):
    cp = Checkpoint(path=tmp_path / "cp.json")
    cp.mark_uploaded("u", "1", "imm-1", was_duplicate=True)
    cp.mark_uploaded("u", "2", "imm-2", was_duplicate=False)
    summary = cp.get_summary()
    assert summary["duplicate"] == 1
    assert summary["uploaded"] == 1
    assert cp.is_uploaded("u", "1") == "imm-1"


def test_mark_linked_is_resumable_like_upload(tmp_path):
    cp = Checkpoint(path=tmp_path / "cp.json")
    cp.mark_linked("u", "9", "imm-ext")
    assert cp.is_uploaded("u", "9") == "imm-ext"
    assert cp.get_summary()["linked"] == 1
    assert cp.get_summary().get("uploaded", 0) == 0


def test_shared_space_done_flag(tmp_path):
    cp = Checkpoint(path=tmp_path / "cp.json")
    assert cp.is_shared_space_done() is False
    cp.mark_shared_space_done()
    assert cp.is_shared_space_done() is True
    cp.save()
    cp2 = Checkpoint(path=tmp_path / "cp.json")
    assert cp2.is_shared_space_done() is True
