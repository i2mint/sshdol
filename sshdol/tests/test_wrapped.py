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


def test_mkdir_bare_unchanged(leaf):
    assert leaf.mkdir("newdir") == ("got", "newdir")
    assert leaf._sftp.made == ["newdir"]


def test_mkdir_method_refuses_under_instance_wrap(leaf):
    view = KeyCodecs.prefixed("sub/")(leaf)
    with pytest.raises(WrappedStoreError):
        view.mkdir("newdir")  # Route A: reaches the bound leaf method
    assert leaf._sftp.made == []


def test_ops_mkdir_maps_key_and_returns_wrapped_view(leaf):
    view = KeyCodecs.prefixed("sub/")(leaf)
    got = mkdir(view, "newdir")
    assert leaf._sftp.made == ["sub", "sub/newdir"]  # parent first; not "newdir"
    assert got == ("got", "sub/newdir")  # the outer __getitem__ ran: key re-mapped


def test_ops_mkdir_bare_store(leaf):
    assert mkdir(leaf, "d") == ("got", "d")
    assert leaf._sftp.made == ["d"]


def test_ops_mkdir_under_class_wrap(leaf, monkeypatch):
    monkeypatch.setattr(SshFiles, "__init__", lambda self, *a, **k: None)
    Wrapped = KeyCodecs.prefixed("sub/")(SshFiles)
    w = Wrapped()
    w.store.__dict__.update(leaf.__dict__)
    mkdir(w, "newdir")
    assert w.store._sftp.made == ["sub", "sub/newdir"]
    with pytest.raises(WrappedStoreError):
        w.mkdir("newdir2")


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
    leaf.sync_to(tmp_path / "dst", delete_local_files_not_in_remote=True)
    cmd = rsync[0]
    assert cmd[-2] == "u@h:/remote/root/" and "--delete" in cmd
    assert cmd[-1] == str(tmp_path / "dst") + "/"


def test_sync_to_refuses_wrapped_source(leaf, rsync, tmp_path):
    view = subdir_view(leaf)
    for call in (
        lambda: view.sync_to(tmp_path / "d", delete_local_files_not_in_remote=True),
        lambda: sync_to(view, tmp_path / "d", delete_local_files_not_in_remote=True),
    ):
        with pytest.raises(WrappedStoreError):
            call()
    assert rsync == [] and not (tmp_path / "d").exists()


def test_sync_to_refuses_wrapped_target(leaf, rsync, tmp_path):
    (tmp_path / "local" / "mirror").mkdir(parents=True)
    tgt = subdir_view(dol.Files(str(tmp_path / "local")), "mirror/")
    with pytest.raises(WrappedStoreError):
        sync_to(leaf, tgt, delete_local_files_not_in_remote=True)
    assert rsync == []


def test_sync_to_bare_dol_files_target_still_works(leaf, rsync, tmp_path):
    (tmp_path / "local").mkdir()
    sync_to(leaf, dol.Files(str(tmp_path / "local")))
    assert rsync[0][-1] == str(tmp_path / "local") + "/"


def test_sync_to_explicit_subdir(leaf, rsync, tmp_path):
    sync_to(leaf, tmp_path / "d", subdir="sub/")
    assert rsync[0][-2] == "u@h:/remote/root/sub/"
    with pytest.raises(KeyError, match="outside rootdir"):
        sync_to(leaf, tmp_path / "d", subdir="../etc")


def test_sync_to_refuses_filter_only_target(leaf, rsync, tmp_path):
    (tmp_path / "local").mkdir()
    tgt = filt_iter(dol.Files(str(tmp_path / "local")), filt=lambda k: k.endswith(".txt"))
    with pytest.raises(WrappedStoreError):
        sync_to(leaf, tgt, delete_local_files_not_in_remote=True)
