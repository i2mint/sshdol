"""A rootdir that does not exist is refused or created, never replaced by the login directory
(i2mint/sshdol#14). Integration tests: they need the SSH test server and skip without one."""

import pytest

from sshdol.base import SshFiles, SshFilesReader
from sshdol.tests.test_base import _ssh_available
from sshdol.tests.utils_for_testing import SSH_TEST_HOST, SSH_TEST_ROOTDIR

pytestmark = pytest.mark.skipif(
    not _ssh_available(), reason="no SSH test server reachable"
)

MISSING = SSH_TEST_ROOTDIR.rstrip("/") + "_missing/a/b"


@pytest.fixture
def admin_sftp():
    admin = SshFiles(host=SSH_TEST_HOST, rootdir=".")  # keep alive: its __del__ closes the sftp
    sftp = admin._sftp
    top = MISSING.rsplit("/a/b", 1)[0]

    def rm_top():
        for sub in (MISSING, MISSING.rsplit("/b", 1)[0], top):
            try:
                for e in sftp.listdir(sub):
                    sftp.remove(f"{sub}/{e}")
                sftp.rmdir(sub)
            except OSError:
                pass

    rm_top()
    yield sftp
    rm_top()


@pytest.mark.parametrize("cls", [SshFilesReader, SshFiles])
@pytest.mark.parametrize("max_levels", [0, None])
def test_missing_rootdir_is_refused(admin_sftp, cls, max_levels):
    with pytest.raises(FileNotFoundError, match="rootdir does not exist"):
        cls(host=SSH_TEST_HOST, rootdir=MISSING, max_levels=max_levels)


def test_create_dirs_creates_the_missing_rootdir(admin_sftp):
    store = SshFiles(host=SSH_TEST_HOST, rootdir=MISSING, create_dirs=True)
    store["f.txt"] = b"x"
    assert admin_sftp.file(MISSING + "/f.txt").read() == b"x"
    assert list(store) == ["f.txt"]


def test_existing_rootdir_unchanged(admin_sftp):
    SshFiles(host=SSH_TEST_HOST, rootdir=SSH_TEST_ROOTDIR, create_dirs=True)


@pytest.mark.parametrize("create_dirs", [False, True])
def test_tilde_rootdir_is_refused_not_created_literally(admin_sftp, create_dirs):
    with pytest.raises(FileNotFoundError, match="expand"):
        SshFiles(host=SSH_TEST_HOST, rootdir="~/nope", create_dirs=create_dirs)
    assert "~" not in admin_sftp.listdir(".")


def test_losing_a_creation_race_is_fine(admin_sftp, monkeypatch):
    import paramiko

    real_stat = paramiko.SFTPClient.stat
    calls = []

    def stat_misses_once(self, path):  # as if the directory appeared right after the check
        if path == MISSING.rsplit("/a/b", 1)[0] and not calls:
            calls.append(path)
            admin_sftp.mkdir(path)
            raise FileNotFoundError(2, path)
        return real_stat(self, path)

    monkeypatch.setattr(paramiko.SFTPClient, "stat", stat_misses_once)
    store = SshFiles(host=SSH_TEST_HOST, rootdir=MISSING, create_dirs=True)
    assert calls and list(store) == []


def test_rootdir_deleted_after_construction_lists_nothing_not_home(admin_sftp):
    store = SshFiles(host=SSH_TEST_HOST, rootdir=MISSING, create_dirs=True, max_levels=None)
    admin_sftp.rmdir(MISSING)
    assert list(store) == [] and "py" not in store
