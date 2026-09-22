# sshdol.base

Base functionality for sshdol.

| read-only          | read-write         |
<br/>
:—– | :—————– | :—————– |
<br/>
bytes  | SshFilesReader     | SshFiles           |
<br/>
text   | SshTextFilesReader | SshTextFiles       |
<br/>

Design notes:

* A hybrid bytes & text store? See [https://github.com/i2mint/dol/discussions/53#discussioncomment-12460364](https://github.com/i2mint/dol/discussions/53#discussioncomment-12460364)

### Functions

| [`escapes_root`](#sshdol.base.escapes_root)(path)              | Whether a (normalized, `/`-separated) key path points outside the root.   |
|----------------------------------------------------------------------------------|---------------------------------------------------------------------------|
| [`get_ssh_config_for_host`](#sshdol.base.get_ssh_config_for_host)(host)   | Get SSH configuration for a specific host from the SSH config file.       |
| [`known_hosts_files`](#sshdol.base.known_hosts_files)([ssh_config]) | The known_hosts files that apply, as OpenSSH chooses them.                |
| [`normalize_path`](#sshdol.base.normalize_path)(path)            | Normalize a path to use forward slashes and handle trailing slashes.      |
| [`read_known_hosts`](#sshdol.base.read_known_hosts)(files)         | Parse known_hosts `files` leniently into a `paramiko.HostKeys`.           |
| [`resolve_host_key_policy`](#sshdol.base.resolve_host_key_policy)([...])  | The paramiko policy for hosts whose key is not in `known_hosts`.          |
| [`split_path`](#sshdol.base.split_path)(path)                | Split a path into directory and file parts.                               |

### Classes

| [`RejectUnknownHostKey`](#sshdol.base.RejectUnknownHostKey)()                           | Refuse hosts whose key is not in known_hosts, with a message saying what to do.   |
|---------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------|
| [`SshFiles`](#sshdol.base.SshFiles)([host, user, password, url, port, ...]) | Read-write interface to files on a remote SSH server.                             |
| [`SshFilesReader`](#sshdol.base.SshFilesReader)([host, user, password, url, ...]) | Read-only interface to files on a remote SSH server.                              |
| [`SshTextFiles`](#sshdol.base.SshTextFiles)([host, user, password, url, ...])   | Read-write interface to text files on a remote SSH server.                        |
| [`SshTextFilesReader`](#sshdol.base.SshTextFilesReader)([host, user, password, ...])  | Read-only interface to text files on a remote SSH server.                         |

### *class* sshdol.base.RejectUnknownHostKey

Bases: `RejectPolicy`

Refuse hosts whose key is not in known_hosts, with a message saying what to do.

#### missing_host_key(client, hostname, key)

Called when an `.SSHClient` receives a server key for a server that
isn’t in either the system or local `.HostKeys` object.  To accept
the key, simply return.  To reject, raised an exception (which will
be passed to the calling application).

### *class* sshdol.base.SshFiles(host=None, , user=None, password=None, url=None, port=22, key_filename=None, rootdir='.', include_hidden=False, include_directories=True, dir_access=True, encoding=None, max_levels=0, create_dirs=False, strict_contains=False, allow_escape=False, missing_host_key_policy=None, \_pinned_host_key=None)

Bases: [`SshFilesReader`](#sshdol.base.SshFilesReader), [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)

Read-write interface to files on a remote SSH server.

### Example

```pycon
>>> s = SshFiles(host="myserver")
>>> s['file.txt'] = b'Hello, world!'
>>> s = SshFiles(host="myserver", encoding="utf-8")
>>> s['file.txt'] = 'Hello, world!'
```

Write to nested paths with directory creation

```pycon
>>> s = SshFiles(host="myserver", create_dirs=True)
>>> s['dir1/dir2/file.txt'] = b'Nested content'
```

#### mkdir(path, exist_ok=False)

Create a directory on the SSH server.

* **Parameters:**
  * **path** – Directory path to create
  * **exist_ok** – If True, don’t raise an error if directory already exists
* **Returns:**
  A new instance for the created directory
* **Return type:**
  [*SshFiles*](#sshdol.base.SshFiles)
* **Raises:**
  [**KeyError**](https://docs.python.org/3/builtins/exceptions.html#KeyError) – If directory cannot be created

#### sync_to(target, , delete_local_files_not_in_remote=False, delete_mode=None, recycle_bin='/home/runner/.local/share/Trash/files', compress=True, extra_args=None)

Synchronize remote rootdir to a local directory using rsync over SSH.

This uses one local rsync invocation, which negotiates efficiently with the
remote over SSH, minimizing round-trips and transferring only deltas.

* **Parameters:**
  * **target** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Local directory to sync into (created if missing).
  * **delete_local_files_not_in_remote** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – If True, remove local files that are not on remote (rsync –delete).
  * **delete_mode** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Literal`](https://docs.python.org/3/library/typing.html#typing.Literal)[`'after'`, `'before'`, `'delay'`, `'during'`, `'recycle'`]]) – 

    Choose when/how deletion occurs. One of:
    - ’before’  -> –delete-before
    - ’after’   -> –delete-after
    - ’delay’   -> –delete-delay
    - ’during’  -> –delete-during
    - ’recycle’ -> move would-be deletions into recycle_bin using –backup/–backup-dir
      If None, rsync uses its default timing when –delete is set.
  * **recycle_bin** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – When delete_mode=’recycle’, directory to store deleted items.
    Defaults to the OS recycle location (macOS: ~/.Trash, Linux: ~/.local/share/Trash/files).
  * **compress** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – If True, use -z compression.
  * **extra_args** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)] | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Additional rsync args (list of strings) to append.
* **Raises:**
  [**RuntimeError**](https://docs.python.org/3/builtins/exceptions.html#RuntimeError) – If rsync is unavailable or the sync fails.
* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### *class* sshdol.base.SshFilesReader(host=None, , user=None, password=None, url=None, port=22, key_filename=None, rootdir='.', include_hidden=False, include_directories=True, dir_access=True, encoding=None, max_levels=0, create_dirs=False, strict_contains=False, allow_escape=False, missing_host_key_policy=None, \_pinned_host_key=None)

Bases: [`Mapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)

Read-only interface to files on a remote SSH server.

### Examples

Connect using an SSH config alias

```pycon
>>> s = SshFilesReader(host="myserver")
```

Connect with explicit parameters

```pycon
>>> s = SshFilesReader(user="username", url="example.com")
```

Access nested files with path-based keys

```pycon
>>> s = SshFilesReader(host="myserver", max_levels=None)
>>> content = s["path/to/nested/file.txt"]
```

### *class* sshdol.base.SshTextFiles(host=None, , user=None, password=None, url=None, port=22, key_filename=None, rootdir='.', include_hidden=False, include_directories=True, dir_access=True, encoding=None, max_levels=0, create_dirs=False, strict_contains=False, allow_escape=False, missing_host_key_policy=None, \_pinned_host_key=None)

Bases: [`SshFiles`](#sshdol.base.SshFiles)

Read-write interface to text files on a remote SSH server.

### *class* sshdol.base.SshTextFilesReader(host=None, , user=None, password=None, url=None, port=22, key_filename=None, rootdir='.', include_hidden=False, include_directories=True, dir_access=True, encoding=None, max_levels=0, create_dirs=False, strict_contains=False, allow_escape=False, missing_host_key_policy=None, \_pinned_host_key=None)

Bases: [`SshFilesReader`](#sshdol.base.SshFilesReader)

Read-only interface to text files on a remote SSH server.

### sshdol.base.escapes_root(path)

Whether a (normalized, `/`-separated) key path points outside the root.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

```pycon
>>> escapes_root('a/b.txt'), escapes_root('a/../b'), escapes_root('')
(False, False, False)
>>> escapes_root('..'), escapes_root('a/../../b'), escapes_root('/etc/x')
(True, True, True)
```

### sshdol.base.get_ssh_config_for_host(host)

Get SSH configuration for a specific host from the SSH config file.

* **Parameters:**
  **host** – The host alias to look up
* **Returns:**
  Dictionary with SSH configuration parameters
* **Return type:**
  [*dict*](https://docs.python.org/3/builtins/stdtypes.html#dict)

### sshdol.base.known_hosts_files(ssh_config=None)

The known_hosts files that apply, as OpenSSH chooses them.

`GlobalKnownHostsFile` / `UserKnownHostsFile` from the host’s ssh config
replace the defaults (`/dev/null` or `none` means “no file”).
Only existing files are returned.

### sshdol.base.normalize_path(path)

Normalize a path to use forward slashes and handle trailing slashes.

* **Parameters:**
  **path** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Path to normalize
* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
* **Returns:**
  Normalized path

### sshdol.base.read_known_hosts(files)

Parse known_hosts `files` leniently into a `paramiko.HostKeys`.

Lines paramiko can’t use (`@cert-authority` / `@revoked` markers, key types
it doesn’t support, malformed or undecodable lines) are skipped instead of
aborting the whole file. Note that `@revoked` entries are therefore not
honoured.

* **Return type:**
  `HostKeys`

### sshdol.base.resolve_host_key_policy(missing_host_key_policy=None, ssh_config=None)

The paramiko policy for hosts whose key is not in `known_hosts`.

An explicit `missing_host_key_policy` (a paramiko policy class or instance)
wins. Otherwise the host’s ssh config decides: `StrictHostKeyChecking` set
to `no`/`off`/`accept-new` accepts (and remembers for the session) an
unknown key; anything else rejects it, as a non-interactive `ssh` would.
A key that *changed* is always refused by paramiko.

```pycon
>>> type(resolve_host_key_policy()).__name__
'RejectUnknownHostKey'
>>> type(resolve_host_key_policy(ssh_config={'stricthostkeychecking': 'accept-new'})).__name__
'AutoAddPolicy'
>>> type(resolve_host_key_policy(paramiko.AutoAddPolicy)).__name__
'AutoAddPolicy'
```

### sshdol.base.split_path(path)

Split a path into directory and file parts.

* **Parameters:**
  **path** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Path to split
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
* **Returns:**
  Tuple of (directory_part, file_part)
