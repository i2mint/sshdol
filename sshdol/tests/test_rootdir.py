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
    sftp = SshFiles(host=SSH_TEST_HOST, rootdir=".")._sftp
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
