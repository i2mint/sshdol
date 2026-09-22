"""Key confinement and host-key policy (no SSH server needed)."""

import paramiko
import pytest

from sshdol.base import (
    RejectUnknownHostKey,
    SshFiles,
    escapes_root,
    resolve_host_key_policy,
)


def _store(**attrs):
    # Bypass __init__ (which connects); only key handling is exercised.
    s = SshFiles.__new__(SshFiles)
    s._allow_escape = False
    s.__dict__.update(attrs)
    return s


@pytest.mark.parametrize(
    "key", ["..", "../x", "a/../../x", "/etc/hosts", "..\\x", "a/b/../../../x"]
)
def test_escaping_keys_are_refused(key):
    s = _store()
    for op in (
        lambda: s[key],
        lambda: s.__setitem__(key, b"x"),
        lambda: s.__delitem__(key),
        lambda: s.mkdir(key),
    ):
        with pytest.raises(KeyError, match="outside rootdir"):
            op()
    assert key not in s


@pytest.mark.parametrize("key", ["a", "a/b.txt", "a/../b", "./a", "a/"])
def test_keys_inside_root_pass(key):
    assert not escapes_root(_store()._key_to_path(key))


def test_allow_escape_opt_in():
    assert _store(_allow_escape=True)._key_to_path("../x") == "../x"


def test_host_key_policy_defaults_to_reject():
    assert isinstance(resolve_host_key_policy(), RejectUnknownHostKey)
    assert isinstance(
        resolve_host_key_policy(ssh_config={"stricthostkeychecking": "yes"}),
        RejectUnknownHostKey,
    )
    with pytest.raises(paramiko.SSHException, match="not in known_hosts"):
        RejectUnknownHostKey().missing_host_key(None, "example.invalid", None)


@pytest.mark.parametrize("value", ["no", "accept-new", "OFF"])
def test_host_key_policy_follows_ssh_config(value):
    policy = resolve_host_key_policy(ssh_config={"stricthostkeychecking": value})
    assert isinstance(policy, paramiko.AutoAddPolicy)


def test_explicit_host_key_policy_wins():
    assert isinstance(
        resolve_host_key_policy(
            paramiko.AutoAddPolicy, {"stricthostkeychecking": "yes"}
        ),
        paramiko.AutoAddPolicy,
    )
    policy = paramiko.WarningPolicy()
    assert resolve_host_key_policy(policy) is policy
