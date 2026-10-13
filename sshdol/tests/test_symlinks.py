"""Symbolic links under rootdir must not lead outside it (i2mint/sshdol#11).

Integration tests: they need the SSH test server (see ``test_base``) and skip without one.
"""

import posixpath

import pytest

from sshdol.base import SshFiles
from sshdol.ops import mkdir, sync_to
from sshdol.tests.test_base import _ssh_available
from sshdol.tests.utils_for_testing import SSH_TEST_HOST, SSH_TEST_ROOTDIR

pytestmark = pytest.mark.skipif(
    not _ssh_available(), reason="no SSH test server reachable"
)

BASE = SSH_TEST_ROOTDIR.rstrip("/") + "_symlinks"  # root/ and outside/ live under it


@pytest.fixture
def stores():
    """(store over BASE/root, sftp, BASE/outside) with a clean slate; removed after."""
    admin = SshFiles(host=SSH_TEST_HOST, rootdir=".")
    sftp = admin._sftp

    def rm_rf(path):
        try:
            entries = sftp.listdir_attr(path)
        except OSError:
            return
        for e in entries:
            child = posixpath.join(path, e.filename)
            if sftp.lstat(child).st_mode & 0o170000 == 0o040000:
                rm_rf(child)
            else:
                sftp.remove(child)
        sftp.rmdir(path)

    rm_rf(BASE)
    for d in (BASE, BASE + "/root", BASE + "/root/sub", BASE + "/outside"):
        sftp.mkdir(d)
    with sftp.file(BASE + "/outside/secret.txt", "wb") as f:
        f.write(b"secret")
    with sftp.file(BASE + "/root/sub/inside.txt", "wb") as f:
        f.write(b"inside")
    store = SshFiles(host=SSH_TEST_HOST, rootdir=BASE + "/root", max_levels=None)
    yield store, sftp, BASE + "/outside"
    rm_rf(BASE)


def test_link_to_outside_file_refused(stores):
    store, sftp, outside = stores
    sftp.symlink(outside + "/secret.txt", BASE + "/root/leak")
    assert "leak" not in store
    with pytest.raises(KeyError, match="symbolic link"):
        store["leak"]
    with pytest.raises(KeyError, match="symbolic link"):
        store["leak"] = b"overwritten"
    assert sftp.file(outside + "/secret.txt").read() == b"secret"


def test_link_to_outside_directory_refused(stores):
    store, sftp, outside = stores
    sftp.symlink(outside, BASE + "/root/out")
    for key in ("out", "out/secret.txt", "out/new.txt"):
        assert key not in store
        with pytest.raises(KeyError, match="symbolic link"):
            store[key]
    with pytest.raises(KeyError, match="symbolic link"):
        store["out/new.txt"] = b"x"
    with pytest.raises(KeyError, match="symbolic link"):
        mkdir(store, "out/newdir")
    assert sftp.listdir(outside) == ["secret.txt"]


def test_relative_link_to_outside_refused(stores):
    store, sftp, _ = stores
    sftp.symlink("../outside/secret.txt", BASE + "/root/rel")
    with pytest.raises(KeyError, match="symbolic link"):
        store["rel"]


def test_dotdot_through_link_resolved_physically(stores):
    store, sftp, _ = stores
    sftp.symlink(BASE + "/outside", BASE + "/root/out")
    # lexically 'out/../x' is root/x; on the server 'out/..' is the parent of outside/
    with pytest.raises(KeyError, match="symbolic link"):
        store["out/../outside/secret.txt"]
    assert store["out/../root/sub/inside.txt"] == b"inside"  # that one is inside


def test_dangling_link_to_outside_refused_for_write(stores):
    store, sftp, outside = stores
    sftp.symlink(outside + "/not_yet.txt", BASE + "/root/dangling")
    with pytest.raises(KeyError, match="symbolic link"):
        store["dangling"] = b"planted"
    assert "not_yet.txt" not in sftp.listdir(outside)


def test_link_loop_refused(stores):
    store, sftp, _ = stores
    sftp.symlink("loop_b", BASE + "/root/loop_a")
    sftp.symlink("loop_a", BASE + "/root/loop_b")
    with pytest.raises(KeyError):
        store["loop_a"] = b"x"


def test_link_inside_root_still_works(stores):
    store, sftp, _ = stores
    sftp.symlink("sub", BASE + "/root/alias")
    assert store["alias/inside.txt"] == b"inside"
    store["alias/new.txt"] = b"n"
    assert store["sub/new.txt"] == b"n"


def test_delete_removes_the_link_not_the_target(stores):
    store, sftp, outside = stores
    sftp.symlink(outside + "/secret.txt", BASE + "/root/leak")
    sftp.symlink(outside, BASE + "/root/out")
    del store["leak"]
    del store["out"]
    assert sorted(sftp.listdir(BASE + "/root")) == ["sub"]
    assert sftp.listdir(outside) == ["secret.txt"]


def test_allow_escape_opts_out(stores):
    _, sftp, outside = stores
    sftp.symlink(outside + "/secret.txt", BASE + "/root/leak")
    store = SshFiles(host=SSH_TEST_HOST, rootdir=BASE + "/root", allow_escape=True)
    assert store["leak"] == b"secret"


def test_sync_to_subdir_symlink_refused_and_links_skipped(stores, tmp_path):
    store, sftp, outside = stores
    sftp.symlink(outside, BASE + "/root/out")
    with pytest.raises(KeyError, match="symbolic link"):
        sync_to(store, tmp_path / "d1", subdir="out")
    sftp.symlink(outside + "/secret.txt", BASE + "/root/sub/leak")
    sync_to(store, tmp_path / "d2")
    assert (tmp_path / "d2" / "sub" / "inside.txt").read_bytes() == b"inside"
    assert not (tmp_path / "d2" / "sub" / "leak").exists()
    assert not (tmp_path / "d2" / "sub" / "leak").is_symlink()


def test_subdir_instance_listing_agrees_with_sftp_on_dotdot_after_link(stores):
    """Shell ``cd`` used to resolve ``..`` by text, listing the outside directory."""
    store, sftp, outside = stores
    sftp.mkdir(BASE + "/root/sub/a")
    sftp.mkdir(BASE + "/root/sub/Y")
    sftp.symlink(BASE + "/root/sub/a", BASE + "/root/deep")
    sftp.symlink(outside, BASE + "/root/Y")
    # physically deep/../Y is root/sub/Y (inside); textually it is root/Y -> outside
    child = store["deep/../Y"]
    assert list(child) == [] and len(child) == 0
    assert "secret.txt" not in child


@pytest.mark.parametrize("flag", ["-L", "--copy-links", "--copy-unsafe-links", "-k"])
def test_sync_to_refuses_link_following_args(stores, tmp_path, flag):
    store, _, _ = stores
    with pytest.raises(ValueError, match="allow_escape"):
        sync_to(store, tmp_path / "d", extra_args=[flag])


# ---- sync_to subdir with characters rsync would split (i2mint/sshdol#12) ----------------


@pytest.mark.parametrize("name", ["my dir", "a;b $x", "quote'd", "ünï cödé"])
def test_sync_to_subdir_with_unusual_characters(stores, tmp_path, name):
    from sshdol.base import PROTECT_ARGS_MIN_RSYNC, local_rsync_version

    if local_rsync_version() < PROTECT_ARGS_MIN_RSYNC:
        pytest.skip("needs rsync >= 3.2.4")
    store, sftp, _ = stores
    sftp.mkdir(BASE + "/root/" + name)
    with sftp.file(BASE + "/root/" + name + "/f.txt", "wb") as f:
        f.write(b"in " + name.encode())
    sync_to(store, tmp_path / "d", subdir=name)
    assert (tmp_path / "d" / "f.txt").read_bytes() == b"in " + name.encode()
    assert not (tmp_path / "d" / "sub").exists()  # only the subdir was synced


def test_sync_to_subdir_unusual_characters_refused_on_old_rsync(
    stores, tmp_path, monkeypatch
):
    import sshdol.base as base

    monkeypatch.setattr(base, "local_rsync_version", lambda: (3, 1, 3))
    store, _, _ = stores
    with pytest.raises(ValueError, match="3.2.4"):
        sync_to(store, tmp_path / "d", subdir="my dir")


def test_sync_to_subdir_control_characters_refused(stores, tmp_path):
    store, _, _ = stores
    with pytest.raises(ValueError, match="control"):
        sync_to(store, tmp_path / "d", subdir="a\nb")


@pytest.mark.parametrize("pattern", ["ln[k]", "l?k", "l*", "*", "[l]nk", "sub/[.][.]"])
def test_sync_to_subdir_wildcards_cannot_reach_through_a_link(stores, tmp_path, pattern):
    """The remote rsync expands wildcards itself, past the symlink check on the literal name."""
    store, sftp, outside = stores
    sftp.symlink(outside, BASE + "/root/lnk")
    with pytest.raises(ValueError, match="wildcard"):
        sync_to(store, tmp_path / "d", subdir=pattern)
    assert not (tmp_path / "d").exists() or not list((tmp_path / "d").iterdir())


@pytest.mark.parametrize(
    "out, expected",
    [
        ("rsync  version 3.4.1  protocol version 32", (3, 4, 1)),
        ("rsync  version v3.2.7  protocol version 31", (3, 2, 7)),
        ("rsync  version 3.2.4pre1  protocol version 31", (3, 2, 4)),
    ],
)
def test_local_rsync_version_parsing(monkeypatch, out, expected):
    import subprocess

    import sshdol.base as base

    monkeypatch.setattr(base, "_rsync_version_cache", None)
    monkeypatch.setattr(
        base.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=out),
    )
    assert base.local_rsync_version() == expected


def test_failed_rsync_version_is_not_cached(monkeypatch):
    import sshdol.base as base

    monkeypatch.setattr(base, "_rsync_version_cache", None)

    def boom(*a, **k):
        raise OSError("no rsync")

    monkeypatch.setattr(base.subprocess, "run", boom)
    assert base.local_rsync_version() == () and base._rsync_version_cache is None
