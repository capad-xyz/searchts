# -*- coding: utf-8 -*-
"""#452: the kept-audio cache: one key per video, 24h, a size cap, off on demand."""

import os
import time

import pytest

from searchts import audio_cache as ac
from searchts.config import Config

DAY = 24 * 60 * 60


@pytest.fixture
def cache_root(tmp_path, monkeypatch):
    root = tmp_path / "audio"
    monkeypatch.setenv("SEARCHTS_AUDIO_CACHE_DIR", str(root))
    return root


def _write(path, data=b"x" * 32):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_youtube_links_of_the_same_video_share_one_key():
    links = [
        "https://youtu.be/dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ?t=40",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&feature=share",
        "http://youtube.com/shorts/dQw4w9WgXcQ",
        "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
    ]
    assert {ac.normalize(link) for link in links} == {"youtube:dQw4w9WgXcQ"}


def test_tracking_parameters_do_not_make_a_new_entry():
    plain = "https://example.test/video/42"
    shared = "https://example.test/video/42?utm_source=chat&utm_medium=copy&fbclid=abc"
    assert ac.normalize(plain) == ac.normalize(shared)
    assert ac.normalize(shared) == "example.test/video/42"


def test_a_real_query_parameter_stays_in_the_key():
    assert (
        ac.normalize("https://example.test/play?id=42")
        != ac.normalize("https://example.test/play?id=43")
    )


def test_local_files_and_odd_schemes_are_never_cached():
    assert ac.normalize("/tmp/clip.m4a") == ""
    assert ac.normalize("clip.m4a") == ""
    assert ac.normalize("file:///tmp/clip.m4a") == ""
    assert ac.entry_path("/tmp/clip.m4a") is None


def test_store_then_lookup_round_trips(cache_root, tmp_path):
    src = _write(tmp_path / "compressed.m4a", b"m4a-bytes")
    kept = ac.store("https://youtu.be/dQw4w9WgXcQ", src)
    assert kept is not None and kept.is_file()
    assert kept.read_bytes() == b"m4a-bytes"
    assert kept.parent == cache_root
    assert ac.lookup("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == kept


def test_an_expired_entry_is_missed_and_removed(cache_root, tmp_path):
    src = _write(tmp_path / "compressed.m4a")
    kept = ac.store("https://youtu.be/dQw4w9WgXcQ", src, now=1_000_000)
    assert ac.lookup("https://youtu.be/dQw4w9WgXcQ", now=1_000_000 + DAY - 1) == kept
    assert ac.lookup("https://youtu.be/dQw4w9WgXcQ", now=1_000_000 + DAY + 1) is None
    assert not kept.exists()


def test_eviction_drops_expired_entries(cache_root):
    # Written by hand: store() sweeps on its own, so this proves evict()'s TTL.
    old = ac.entry_path("https://youtu.be/aaaaaaaaaaa")
    fresh = ac.entry_path("https://youtu.be/bbbbbbbbbbb")
    for path, stamp in ((old, 1_000), (fresh, 1_000 + DAY + 5)):
        _write(path)
        os.utime(path, (stamp, stamp))
    removed = ac.evict(now=1_000 + DAY + 10)
    assert removed == [old]
    assert not old.exists() and fresh.exists()


def test_size_cap_evicts_the_oldest_first(cache_root, tmp_path):
    now = time.time()
    entries = []
    for index, name in enumerate(("aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc")):
        path = _write(tmp_path / f"{name}.m4a", b"x" * 100)
        os.utime(path, (now - 300 + index, now - 300 + index))
        kept = ac.store(f"https://youtu.be/{name}", path, now=now - 300 + index)
        os.utime(kept, (now - 300 + index, now - 300 + index))
        entries.append(kept)
    # 300 bytes held, cap 150: the two oldest go, the newest stays.
    removed = ac.evict(max_bytes=150, now=now)
    assert removed == entries[:2]
    assert [entry.exists() for entry in entries] == [False, False, True]
    assert ac.lookup("https://youtu.be/ccccccccccc", now=now) == entries[2]


def test_an_interrupted_store_leaves_nothing_behind(cache_root, tmp_path):
    def not_a_file(*a, **k):
        raise OSError("disk full")

    monkeypatch_target = ac.shutil
    original = monkeypatch_target.copyfile

    def boom(src, dst):
        raise OSError("disk full")

    ac.shutil.copyfile, saved = boom, original
    try:
        assert ac.store("https://youtu.be/dQw4w9WgXcQ", tmp_path / "a.m4a") is None
    finally:
        ac.shutil.copyfile = saved
    assert ac.info()["files"] == 0


def test_caching_can_be_turned_off(cache_root, monkeypatch):
    cfg = Config(config_path=None)
    assert ac.enabled(cfg) is True
    monkeypatch.setenv("SEARCHTS_AUDIO_CACHE", "0")
    assert ac.enabled(cfg) is False
    monkeypatch.delenv("SEARCHTS_AUDIO_CACHE")
    monkeypatch.setattr(cfg, "get", lambda key, default=None: "off" if key == "audio_cache" else default)
    assert ac.enabled(cfg) is False


def test_info_lists_the_folder_and_its_size(cache_root, tmp_path):
    ac.store("https://youtu.be/dQw4w9WgXcQ", _write(tmp_path / "a.m4a", b"x" * 50))
    data = ac.info()
    assert data["path"] == str(cache_root)
    assert data["exists"] and data["files"] == 1
    assert data["size_bytes"] == 50 and data["size"] == "50 B"
    assert data["ttl_hours"] == 24


def test_clear_removes_the_folder(cache_root, tmp_path):
    ac.store("https://youtu.be/dQw4w9WgXcQ", _write(tmp_path / "a.m4a"))
    assert ac.clear() == [str(cache_root)]
    assert not cache_root.exists()
    assert ac.clear() == []
