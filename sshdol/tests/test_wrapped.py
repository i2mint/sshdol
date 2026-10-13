"""Key-transform blindness (i2mint/sshdol#6): wrapped stores, no SSH server needed."""

import subprocess
from unittest import mock

import dol
import pytest
from dol import KeyCodecs, filt_iter

import sshdol.base as base
from sshdol.base import SshFiles, WrappedStoreError
from sshdol.ops import mkdir, sync_to


class Recorder:
    def __init__(self):
        self.made = []

    def mkdir(self, path):
        self.made.append(path)

    def stat(self, path):
        raise OSError(path)


@pytest.fixture
def leaf(monkeypatch):
    s = SshFiles.__new__(SshFiles)
    s.__dict__.update(
        _allow_escape=False,
        _create_dirs=True,
        rootdir="/remote/root",
        _conn_user="u",
        _conn_host="h",
        _conn_port=22,
        _conn_key_filename=None,
        _sftp=Recorder(),
    )
    monkeypatch.setattr(SshFiles, "_path_exists", lambda self, p: False)
    monkeypatch.setattr(SshFiles, "_is_dir", lambda self, p: False)
    monkeypatch.setattr(SshFiles, "__getitem__", lambda self, k: ("got", k))
    return s


def subdir_view(store, prefix="sub/"):
    return KeyCodecs.prefixed(prefix)(filt_iter(store, filt=lambda k: k.startswith(prefix)))


def test_mkdir_and_sync_to_methods_removed_with_replacement_named(leaf):
    with pytest.raises(AttributeError, match=r"sshdol\.ops\.mkdir"):
        leaf.mkdir("d")
    with pytest.raises(AttributeError, match=r"sshdol\.ops\.sync_to"):
        leaf.sync_to("/tmp/x")
    # ... also when reached through any wrapper, inline or held (no detection needed)
    with pytest.raises(AttributeError):
        KeyCodecs.prefixed("sub/")(leaf).mkdir("d")
    with pytest.raises(AttributeError):
        KeyCodecs.prefixed("sub/")(leaf).sync_to("/tmp/x", delete_local_files_not_in_remote=True)
    assert leaf._sftp.made == []


def test_ops_mkdir_maps_key_and_returns_wrapped_view(leaf):
    view = KeyCodecs.prefixed("sub/")(leaf)
    assert mkdir(view, "newdir") is None
    assert leaf._sftp.made == ["sub", "sub/newdir"]  # parent first; not "newdir"


def test_ops_mkdir_bare_store(leaf):
    mkdir(leaf, "d")
    assert leaf._sftp.made == ["d"]


def test_ops_mkdir_under_class_wrap(leaf, monkeypatch):
    monkeypatch.setattr(SshFiles, "__init__", lambda self, *a, **k: None)
    Wrapped = KeyCodecs.prefixed("sub/")(SshFiles)
    w = Wrapped()
    w.store.__dict__.update(leaf.__dict__)
    mkdir(w, "newdir")
    assert w.store._sftp.made == ["sub", "sub/newdir"]


def test_ops_mkdir_pathlike_inner_key(leaf):
    import pathlib

    view = dol.wrap_kvs(leaf, id_of_key=lambda k: pathlib.PurePosixPath("sub") / k)
    mkdir(view, "nd")
    assert leaf._sftp.made == ["sub", "sub/nd"]


def test_ops_mkdir_still_confined_to_rootdir(leaf):
    view = KeyCodecs.prefixed("../")(leaf)
    with pytest.raises(KeyError, match="outside rootdir"):
        mkdir(view, "x")


def test_mkdir_rejects_reader():
    from sshdol.base import SshFilesReader

    r = SshFilesReader.__new__(SshFilesReader)
    with pytest.raises(TypeError):
        mkdir(r, "x")


@pytest.fixture
def rsync(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(base.shutil, "which", lambda name: "/usr/bin/rsync")
    monkeypatch.setattr(
        base.subprocess,
        "run",
        lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0),
    )
    return calls


def test_sync_to_bare_unchanged(leaf, rsync, tmp_path):
    sync_to(leaf, tmp_path / "dst", delete_local_files_not_in_remote=True)
    cmd = rsync[0]
    assert cmd[-2] == "u@h:/remote/root/" and "--delete" in cmd
    assert cmd[-1] == str(tmp_path / "dst") + "/"


def test_sync_to_refuses_wrapped_source(leaf, rsync, tmp_path):
    for view in (
        subdir_view(leaf),
        filt_iter(leaf, filt=lambda k: k.startswith("sub/")),
        KeyCodecs.prefixed("sub/")(leaf),
    ):
        with pytest.raises(WrappedStoreError):
            sync_to(view, tmp_path / "d", delete_local_files_not_in_remote=True)
    assert rsync == [] and not (tmp_path / "d").exists()


def test_sync_to_bare_store_unaffected_by_live_wrapper(leaf, rsync, tmp_path):
    view = KeyCodecs.prefixed("sub/")(leaf)  # a sibling wrapper exists: leaf is still bare
    sync_to(leaf, tmp_path / "d")
    assert len(rsync) == 1 and view is not None


@pytest.fixture
def local(tmp_path):
    (tmp_path / "local" / "mirror").mkdir(parents=True)
    return tmp_path / "local"


def test_sync_to_refuses_every_object_target(leaf, rsync, local):
    root = str(local)

    class Plain:  # the formerly documented "anything with a .rootdir"
        rootdir = root

    targets = {
        "plain dol.Files": dol.Files(root),
        "max_levels": dol.Files(root, max_levels=0),
        "prefixed instance": subdir_view(dol.Files(root), "mirror/"),
        "filter class wrap": filt_iter(filt=lambda k: k.endswith(".txt"))(dol.Files)(root),
        "subpath": dol.Files(root, subpath="mirror"),
        "plain object": Plain(),
    }
    for name, tgt in targets.items():
        with pytest.raises(WrappedStoreError):
            sync_to(leaf, tgt, delete_local_files_not_in_remote=True)
    assert rsync == []


def test_sync_to_pathlike_target_ok(leaf, rsync, local):
    sync_to(leaf, local)
    assert rsync[0][-1] == str(local) + "/"


def test_sync_to_explicit_subdir(leaf, rsync, tmp_path):
    sync_to(leaf, tmp_path / "d", subdir="sub/")
    assert rsync[0][-2] == "u@h:/remote/root/sub/"
    with pytest.raises(KeyError, match="outside rootdir"):
        sync_to(leaf, tmp_path / "d", subdir="../etc")


@pytest.mark.parametrize("bad", ["a b", "x;rm -rf ~", "$(id)", "a`id`"])
def test_sync_to_subdir_metacharacters_refused(leaf, rsync, tmp_path, bad):
    with pytest.raises(ValueError, match="subdir"):
        sync_to(leaf, tmp_path / "d", subdir=bad)
    assert rsync == []
