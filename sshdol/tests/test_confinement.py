"""Key confinement and host-key policy (no SSH server needed)."""

import paramiko
import pytest

from sshdol.base import (
    RejectUnknownHostKey,
    SshFiles,
    _seed_host_keys,
    escapes_root,
    known_hosts_files,
    read_known_hosts,
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


@pytest.mark.parametrize(
    "key, path", [("a", "a"), ("a/b.txt", "a/b.txt"), ("a/../b", "a/../b"), ("a/", "a")]
)
def test_keys_inside_root_pass(key, path):
    assert _store()._key_to_path(key) == path


def test_nul_in_key_refused():
    with pytest.raises(KeyError, match="NUL"):
        _store()._key_to_path("..\x00x")


def test_escaping_key_not_contained_even_when_strict():
    s = _store(_max_levels=None, _strict_contains=True)
    assert "../x" not in s


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


@pytest.fixture
def ecdsa_key():
    return paramiko.ECDSAKey.generate()


def _line(host, key):
    return f"{host} {key.get_name()} {key.get_base64()}"


def test_read_known_hosts_skips_unusable_lines(tmp_path, ecdsa_key):
    f = tmp_path / "known_hosts"
    f.write_bytes(
        "\n".join(
            [
                "# comment",
                "@cert-authority *.example.org " + ecdsa_key.get_name() + " AAAA",
                "@revoked other.example " + ecdsa_key.get_name() + " AAAA",
                "garbage line",
                "bad.example ssh-ed25519 !!!notbase64!!!",
            ]
        ).encode()
        + b"\n\xff\xfe not utf8\n"
        + _line("good.example", ecdsa_key).encode()
        + b"\n"
    )
    known = read_known_hosts([str(f)])
    assert known.lookup("good.example")[ecdsa_key.get_name()] == ecdsa_key


def test_known_hosts_files_follow_ssh_config(tmp_path):
    custom = tmp_path / "kh"
    custom.write_text("")
    assert known_hosts_files(
        {"userknownhostsfile": str(custom), "globalknownhostsfile": "/dev/null"}
    ) == [str(custom)]
    assert (
        known_hosts_files(
            {"userknownhostsfile": "/dev/null", "globalknownhostsfile": "none"}
        )
        == []
    )


def test_seed_host_keys_matches_case_and_alias(ecdsa_key):
    known = paramiko.HostKeys()
    known.add("myhost.example", ecdsa_key.get_name(), ecdsa_key)
    known.add("[aliased]:2222", ecdsa_key.get_name(), ecdsa_key)

    client = paramiko.SSHClient()
    _seed_host_keys(client, known, hostname="MyHost.Example")
    assert client.get_host_keys().lookup("MyHost.Example")

    client = paramiko.SSHClient()
    _seed_host_keys(client, known, hostname="10.0.0.1", port=2222, alias="aliased")
    assert client.get_host_keys().lookup("[10.0.0.1]:2222")
