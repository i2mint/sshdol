"""
Base functionality for sshdol.

|        | read-only          | read-write         |
| :----- | :----------------- | :----------------- |
| bytes  | SshFilesReader     | SshFiles           |
| text   | SshTextFilesReader | SshTextFiles       |

Design notes:

* A hybrid bytes & text store? See https://github.com/i2mint/dol/discussions/53#discussioncomment-12460364

"""

from pathlib import Path
from typing import (
    Mapping,
    MutableMapping,
    Iterator,
    Any,
    Optional,
    List,
    Tuple,
    Union,
    Literal,
)
import os
import stat
import subprocess
import shutil
import sys
import paramiko
from functools import lru_cache
import shlex

places_to_look_for_default_key = ["~/.ssh/id_rsa", "~/.ssh/id_ed25519"]


def get_ssh_config_for_host(host):
    """
    Get SSH configuration for a specific host from the SSH config file.

    Args:
        host: The host alias to look up

    Returns:
        dict: Dictionary with SSH configuration parameters
    """
    ssh_config_path = os.path.expanduser("~/.ssh/config")

    if not os.path.exists(ssh_config_path):
        return {}

    config = paramiko.SSHConfig()
    with open(ssh_config_path) as f:
        config.parse(f)

    return config.lookup(host)


def normalize_path(path: str) -> str:
    """
    Normalize a path to use forward slashes and handle trailing slashes.

    Args:
        path: Path to normalize

    Returns:
        Normalized path
    """
    # Handle empty paths and root directory
    if not path or path == ".":
        return ""

    # Remove trailing slash if present
    path = path[:-1] if path.endswith("/") else path

    # Normalize path separators to forward slashes
    return path.replace("\\", "/")


def split_path(path: str) -> Tuple[str, str]:
    """
    Split a path into directory and file parts.

    Args:
        path: Path to split

    Returns:
        Tuple of (directory_part, file_part)
    """
    path = normalize_path(path)

    if "/" not in path:
        return "", path

    parts = path.split("/")
    return "/".join(parts[:-1]), parts[-1]


class SshFilesReader(Mapping):
    """
    Read-only interface to files on a remote SSH server.

    Examples:

    Connect using an SSH config alias

    >>> s = SshFilesReader(host="myserver")  # doctest: +SKIP

    Connect with explicit parameters

    >>> s = SshFilesReader(user="username", url="example.com")  # doctest: +SKIP

    Access nested files with path-based keys

    >>> s = SshFilesReader(host="myserver", max_levels=None)  # doctest: +SKIP
    >>> content = s["path/to/nested/file.txt"]  # doctest: +SKIP

    """

    __default_encoding = None

    def __init__(
        self,
        host=None,
        *,
        user=None,
        password=None,
        url=None,
        port=22,
        key_filename=None,
        rootdir=".",
        include_hidden=False,
        include_directories=True,  # Whether to include directories in iterations
        dir_access=True,  # Whether to allow accessing directories via __getitem__
        encoding=None,
        max_levels=0,
        create_dirs=False,  # Only relevant for writable stores
        strict_contains=False,  # Whether to raise KeyError or return False for deep paths in __contains__
    ):
        """
        Initialize an SSH connection with read-only file access.

        Args:
            host: SSH alias from config file (if provided, can auto-detect other params)
            user: SSH username
            password: SSH password (if not using key-based auth)
            url: Server hostname or IP address
            port: SSH port
            key_filename: Path to SSH private key file
            rootdir: Base directory to use on the server
            include_hidden: Whether to include hidden files in iterations
            include_directories: Whether to include directories in iterations
            dir_access: Whether to allow accessing directories via __getitem__
            encoding: Text encoding to use (None means use bytes)
            max_levels: Maximum directory depth for recursive operations:
                       0 = current directory only (default)
                       n = n levels of subdirectories
                       None = unlimited depth
                       (Design notes: https://github.com/i2mint/sshdol/issues/1#issue-2910364290)
            create_dirs: Whether to create missing directories on write
                       (only relevant for writable stores)
            strict_contains: If True, __contains__ will raise KeyError for paths beyond max_levels
                            If False (default), it will return False for such paths
                            Design notes: https://github.com/i2mint/sshdol/issues/1#issuecomment-2714508482
        """
        # Store initialization parameters
        self._init_params = {
            "host": host,
            "user": user,
            "password": password,
            "url": url,
            "port": port,
            "key_filename": key_filename,
            "include_hidden": include_hidden,
            "include_directories": include_directories,  # Save the new parameter
            "dir_access": dir_access,  # Save the new parameter
            "encoding": encoding,
            "max_levels": max_levels,
            "create_dirs": create_dirs,
            "strict_contains": strict_contains,
        }

        # Store configuration options
        self._encoding = encoding or self.__default_encoding
        self._max_levels = max_levels
        self._create_dirs = create_dirs
        self._strict_contains = strict_contains
        self._include_hidden = include_hidden
        self._include_directories = include_directories  # Store the new parameter
        self._dir_access = dir_access  # Store the new parameter

        assert self._encoding is None or isinstance(
            self._encoding, str
        ), "Encoding must be a string"

        # Initialize the SSH connection
        self._ssh = paramiko.SSHClient()
        self._ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        # If a host alias is provided, try to get config from SSH config file
        if host and not all([user, url]):
            ssh_config = get_ssh_config_for_host(host)

            # Use values from config if not explicitly provided
            user = user or ssh_config.get("user")
            url = url or ssh_config.get("hostname")
            port = port if port != 22 else int(ssh_config.get("port", 22))

            # Try to use identity file from config if no key specified
            if not key_filename and "identityfile" in ssh_config:
                key_filename = ssh_config["identityfile"][0]

        # Expand key filename if provided
        if key_filename:
            key_filename = os.path.expanduser(key_filename)

        # Default identity files if nothing specified
        if not password and not key_filename:
            for default_key in places_to_look_for_default_key:
                expanded_path = os.path.expanduser(default_key)
                if os.path.exists(expanded_path):
                    key_filename = expanded_path
                    break

        # Connect using appropriate authentication method
        if key_filename:
            self._ssh.connect(url, port=port, username=user, key_filename=key_filename)
        else:
            self._ssh.connect(url, port=port, username=user, password=password)

        self._sftp = self._ssh.open_sftp()
        self.rootdir = rootdir
        # Save connection details for auxiliary operations like rsync
        self._conn_user = user
        self._conn_host = url
        self._conn_port = port
        self._conn_key_filename = key_filename

        # Change to root directory if it's not the default
        if rootdir != ".":
            try:
                self._sftp.chdir(rootdir)
            except IOError:
                # If directory doesn't exist, don't error - it will be handled by operations
                pass

    def _is_dir(self, path):
        """Check if a path is a directory"""
        try:
            attr = self._sftp.stat(path)
            return stat.S_ISDIR(attr.st_mode)
        except IOError:
            return False

    def _path_exists(self, path):
        """Check if a path exists (uses a single remote exec for efficiency)."""
        try:
            # Use a remote shell to test existence relative to rootdir
            quoted_root = shlex.quote(self.rootdir)
            quoted_path = shlex.quote(normalize_path(path))
            cmd = (
                f"cd {quoted_root} 2>/dev/null || true; "
                f"if [ -e {quoted_path} ]; then echo 0; else echo 1; fi"
            )
            stdin, stdout, stderr = self._ssh.exec_command(cmd)
            exit_code_str = stdout.read().decode().strip()
            return exit_code_str == "0"
        except Exception:
            return False

    def _list_directory(self, path="."):
        """List files and directories in the specified path"""
        try:
            entries = self._sftp.listdir(path)
            if not self._include_hidden:
                entries = [e for e in entries if not e.startswith(".")]
            return entries
        except Exception as e:
            print(f"Warning: Error listing directory {path}: {e}")
            return []

    def _walk_directory(self, path=".", current_level=0, max_levels=None):
        """
        Recursively walk a directory and yield entries with their paths using a
        single remote command when possible to minimize SFTP chatter.

        Yields:
            tuple: (path, is_dir) for each entry, relative to the current rootdir
        """
        # Fallback to original SFTP-based approach only for the trivial case of max_levels == 0
        if max_levels == 0:
            try:
                entries = self._list_directory(path)
                for entry in entries:
                    entry_path = f"{path}/{entry}" if path != "." else entry
                    yield entry_path, self._is_dir(entry_path)
            except Exception as e:
                print(f"Warning: Error walking directory {path}: {e}")
            return

        # Build a single 'find' command on the remote to list files/dirs
        try:
            quoted_root = shlex.quote(self.rootdir)
            # Depth mapping: entries at depth 1 correspond to children of '.'
            maxdepth_clause = (
                f"-maxdepth {max_levels + 1} " if max_levels is not None else ""
            )
            # Prune hidden files/dirs if needed
            prune_hidden = (
                "\\( -path './.*' -o -path '*/.*' \\) -prune -o "
                if not self._include_hidden
                else ""
            )
            # Use -printf to get type and relative path (%P removes leading ./)
            find_cmd = (
                f"find . -mindepth 1 {maxdepth_clause}{prune_hidden}-printf '%y\t%P\n'"
            )
            cmd = f"set -e; cd {quoted_root} 2>/dev/null || true; {find_cmd}"
            stdin, stdout, stderr = self._ssh.exec_command(cmd)
            data = stdout.read()
            text = (
                data.decode(errors="ignore")
                if isinstance(data, (bytes, bytearray))
                else str(data)
            )
            for line in text.splitlines():
                line = line.rstrip("\n")
                if not line:
                    continue
                try:
                    ftype, relpath = line.split("\t", 1)
                except ValueError:
                    continue
                is_dir = ftype == "d"
                yield relpath, is_dir
        except Exception as e:
            print(f"Warning: Error walking directory using exec_command: {e}")

    def _check_path_depth(self, path):
        """
        Check if path exceeds maximum allowed depth.

        Args:
            path: Path to check

        Returns:
            bool: True if path is within allowed depth, False otherwise

        Raises:
            KeyError: If path exceeds max_levels
        """
        if self._max_levels is None:
            # No depth restriction
            return True

        # Count the number of directory separators to determine depth
        normalized_path = normalize_path(path)

        # Skip empty paths
        if not normalized_path:
            return True

        depth = normalized_path.count("/")

        if depth > self._max_levels:
            raise KeyError(
                f"Path depth ({depth}) exceeds maximum allowed depth ({self._max_levels}): {path}"
            )
        return True

    def __getitem__(self, k):
        """
        Get contents of a file or return a new instance for directories.
        Supports path-based keys with slashes for nested files.
        Respects max_levels constraint for reading.
        """
        path = normalize_path(k)

        # Check if path exceeds allowed depth
        self._check_path_depth(path)

        # First, check if it's a directory
        is_dir = self._is_dir(path)

        # If this is a directory and dir_access is False, block access immediately
        if is_dir and not self._dir_access:
            raise KeyError(f"Directory access is disabled: {path}")

        # If the key contains slashes, it might be a nested path
        if "/" in path:
            dir_part, file_part = split_path(path)

            # Check if directory part exists
            if dir_part and not self._path_exists(dir_part):
                raise KeyError(f"Directory part does not exist: {dir_part}")

            # Check if the whole path is a directory
            if is_dir:
                # Create a new instance for this subdirectory
                params = self._init_params.copy()

                # Create new path by joining current rootdir with the key
                if self.rootdir == ".":
                    new_rootdir = path
                else:
                    new_rootdir = (
                        f"{self.rootdir}/{path}"
                        if not self.rootdir.endswith("/")
                        else f"{self.rootdir}{path}"
                    )

                # Create a completely new connection for the subdirectory
                new_instance = type(self)(**params, rootdir=new_rootdir)
                return new_instance

            # Try to open as a file
            try:
                with self._sftp.file(path, "rb") as f:
                    content = f.read()
                    # If encoding is specified, decode the bytes to string
                    if self._encoding is not None:
                        content = content.decode(self._encoding)
                    return content
            except Exception as e:
                raise KeyError(f"Error reading file {k}: {str(e)}")

        # Handle direct directory or file access (no slashes)
        if is_dir:
            # Create a new instance for this subdirectory
            params = self._init_params.copy()

            # Create new path by joining current rootdir with the key
            if self.rootdir == ".":
                new_rootdir = path
            else:
                new_rootdir = (
                    f"{self.rootdir}/{path}"
                    if not self.rootdir.endswith("/")
                    else f"{self.rootdir}{path}"
                )

            # Create a completely new connection for the subdirectory
            new_instance = type(self)(**params, rootdir=new_rootdir)
            return new_instance

        # If it's a file, return its contents
        try:
            with self._sftp.file(path, "rb") as f:
                content = f.read()
                # If encoding is specified, decode the bytes to string
                if self._encoding is not None:
                    content = content.decode(self._encoding)
                return content
        except Exception as e:
            raise KeyError(f"Error reading file {k}: {str(e)}")

    def __iter__(self):
        """
        Iterate over files and subdirectories recursively based on max_levels.
        Respects include_directories setting to control whether directories are yielded.
        """
        max_levels = self._max_levels

        if max_levels == 0:
            # Single-level listing can remain SFTP-based for simplicity
            entries = self._list_directory(".")
            for entry in entries:
                if self._is_dir(entry):
                    if self._include_directories:
                        yield f"{entry}/"
                else:
                    yield entry
            return

        # Recursive/Unlimited: use single remote 'find' for efficiency
        seen = set()
        for path, is_dir in self._walk_directory(".", 0, max_levels):
            if is_dir:
                if self._include_directories:
                    key = f"{path}/"
                    if key not in seen:
                        seen.add(key)
                        yield key
            else:
                if path not in seen:
                    seen.add(path)
                    yield path

    def __len__(self):
        """
        Return the number of entries up to max_levels deep.
        """
        try:
            # Use remote count via find to avoid streaming all results back
            quoted_root = shlex.quote(self.rootdir)
            max_levels = self._max_levels
            maxdepth_clause = (
                f"-maxdepth {max_levels + 1} " if max_levels is not None else ""
            )
            prune_hidden = (
                "\\( -path './.*' -o -path '*/.*' \\) -prune -o "
                if not self._include_hidden
                else ""
            )
            if self._include_directories:
                type_clause = "\\( -type f -o -type d \\)"
            else:
                type_clause = "-type f"
            find_cmd = f"find . -mindepth 1 {maxdepth_clause}{prune_hidden}{type_clause} -print | wc -l"
            cmd = f"set -e; cd {quoted_root} 2>/dev/null || true; {find_cmd}"
            stdin, stdout, stderr = self._ssh.exec_command(cmd)
            out = stdout.read().decode().strip()
            return int(out) if out.isdigit() else 0
        except Exception:
            # Fallback to iterating if remote counting fails
            return sum(1 for _ in self)

    def __contains__(self, k):
        """
        Check if a file or directory exists.
        Supports path-based keys with slashes for nested files.
        Respects max_levels constraint based on strict_contains setting.

        See https://github.com/i2mint/sshdol/issues/1#issuecomment-2714508482
        """
        path = normalize_path(k)

        # Check if path exceeds allowed depth
        if self._max_levels is not None and path.count("/") > self._max_levels:
            if self._strict_contains:
                # In strict mode, raise error for paths beyond max_levels
                self._check_path_depth(path)  # This will raise the appropriate KeyError

            # In non-strict mode, just return False for paths beyond max_levels
            return False

        # For direct contains check, use efficient remote existence test
        return self._path_exists(path)

    def __del__(self):
        """Close the SSH connection when the object is deleted"""
        try:
            if hasattr(self, "_sftp"):
                self._sftp.close()
            if hasattr(self, "_ssh"):
                self._ssh.close()
        except:
            pass

    def __repr__(self):
        """String representation of the object"""
        return f"{self.__class__.__name__}(rootdir='{self.rootdir}')"


class SshFiles(SshFilesReader, MutableMapping):
    """
    Read-write interface to files on a remote SSH server.

    Example:

        >>> s = SshFiles(host="myserver")  # doctest: +SKIP
        >>> s['file.txt'] = b'Hello, world!'  # doctest: +SKIP
        >>> s = SshFiles(host="myserver", encoding="utf-8")  # doctest: +SKIP
        >>> s['file.txt'] = 'Hello, world!'  # doctest: +SKIP

        Write to nested paths with directory creation
        
        >>> s = SshFiles(host="myserver", create_dirs=True)  # doctest: +SKIP
        >>> s['dir1/dir2/file.txt'] = b'Nested content'  # doctest: +SKIP
    """

    def _ensure_directory_exists(self, dir_path):
        """
        Ensure a directory exists, creating it if necessary.

        Args:
            dir_path: Directory path to ensure

        Returns:
            bool: True if successful

        Raises:
            KeyError: If directory cannot be created
        """
        if not dir_path or dir_path == ".":
            return True

        # Check if directory already exists
        try:
            self._sftp.stat(dir_path)
            if self._is_dir(dir_path):
                return True
            else:
                raise KeyError(f"Path exists but is not a directory: {dir_path}")
        except IOError:
            # Directory doesn't exist, create it if allowed
            if not self._create_dirs:
                raise KeyError(
                    f"Directory does not exist and create_dirs=False: {dir_path}"
                )

            # Create parent directories recursively
            parent_dir, _ = split_path(dir_path)
            if parent_dir:
                self._ensure_directory_exists(parent_dir)

            # Create the directory
            try:
                self._sftp.mkdir(dir_path)
                return True
            except Exception as e:
                raise KeyError(f"Failed to create directory {dir_path}: {str(e)}")

    def __setitem__(self, k, v):
        """
        Write data to a file on the SSH server.
        Supports path-based keys with slashes for nested files.
        Respects max_levels constraint for writing.
        """
        # Check if path exceeds allowed depth
        path = normalize_path(k)
        self._check_path_depth(path)

        # Handle encoding based on the _encoding attribute
        if self._encoding is not None:
            # When encoding is set, user should provide strings that we then encode
            if isinstance(v, str):
                v = v.encode(self._encoding)
            else:
                raise TypeError(
                    f"When encoding is set to '{self._encoding}', value must be a string"
                )
        else:
            # When no encoding is set, user should provide bytes directly
            if not isinstance(v, bytes):
                raise TypeError("When encoding is None, value must be bytes")

        # If the key contains slashes, ensure parent directories exist
        if "/" in path:
            dir_part, _ = split_path(path)
            if dir_part:
                self._ensure_directory_exists(dir_part)

        # Write the file
        try:
            with self._sftp.file(path, "wb") as f:
                f.write(v)
        except Exception as e:
            raise KeyError(f"Error writing to file {k}: {str(e)}")

    def __delitem__(self, k):
        """
        Delete a file on the SSH server.
        """
        path = normalize_path(k)

        if not self._path_exists(path):
            raise KeyError(k)

        try:
            # Check if it's a directory
            if self._is_dir(path):
                # Check if it's empty
                entries = self._list_directory(path)
                if entries:
                    raise KeyError(f"Cannot delete non-empty directory: {path}")
                self._sftp.rmdir(path)
            else:
                self._sftp.remove(path)
        except Exception as e:
            if isinstance(e, KeyError):
                raise
            raise KeyError(f"Error deleting {k}: {str(e)}")

    def mkdir(self, path, exist_ok=False):
        """
        Create a directory on the SSH server.

        Args:
            path: Directory path to create
            exist_ok: If True, don't raise an error if directory already exists

        Returns:
            SshFiles: A new instance for the created directory

        Raises:
            KeyError: If directory cannot be created
        """
        path = normalize_path(path)

        # Check if directory already exists
        if self._path_exists(path):
            if self._is_dir(path):
                if not exist_ok:
                    raise KeyError(f"Directory already exists: {path}")
            else:
                raise KeyError(f"Path exists but is not a directory: {path}")
        else:
            # Create parent directories recursively
            dir_part, _ = split_path(path)
            if dir_part:
                self._ensure_directory_exists(dir_part)

            # Create the directory
            try:
                self._sftp.mkdir(path)
            except Exception as e:
                raise KeyError(f"Failed to create directory {path}: {str(e)}")

        # Return a new instance for the created directory
        return self[path]

    # -----------------------
    # High-performance syncs
    # -----------------------
    def sync_to(
        self,
        target: str,
        *,
        delete_local_files_not_in_remote: bool = False,
        delete_mode: Optional[
            Literal["after", "before", "delay", "during", "recycle"]
        ] = None,
        recycle_bin: Optional[str] = None,
        compress: bool = True,
        extra_args: Optional[List[str]] = None,
    ) -> None:
        """Synchronize remote rootdir to a local directory using rsync over SSH.

        This uses one local rsync invocation, which negotiates efficiently with the
        remote over SSH, minimizing round-trips and transferring only deltas.

        Args:
            target: Local directory to sync into (created if missing).
            delete_local_files_not_in_remote: If True, remove local files that are not on remote (rsync --delete).
            delete_mode: Choose when/how deletion occurs. One of:
                - 'before'  -> --delete-before
                - 'after'   -> --delete-after
                - 'delay'   -> --delete-delay
                - 'during'  -> --delete-during
                - 'recycle' -> move would-be deletions into recycle_bin using --backup/--backup-dir
                If None, rsync uses its default timing when --delete is set.
            recycle_bin: When delete_mode='recycle', directory to store deleted items.
                Defaults to the OS recycle location (macOS: ~/.Trash, Linux: ~/.local/share/Trash/files).
            compress: If True, use -z compression.
            extra_args: Additional rsync args (list of strings) to append.

        Raises:
            RuntimeError: If rsync is unavailable or the sync fails.
        """
        if isinstance(target, Path):
            target = str(target)
        elif (
            not isinstance(target, str)  # target is not a string
            and hasattr(target, "rootdir")  # and has a rootdir attribute
            and isinstance(target.rootdir, str)  # which is a string
            and os.path.exists(target.rootdir)  # and exists as a directory
        ):  # then take that as the target
            target = target.rootdir

        # Ensure local destination exists
        os.makedirs(target, exist_ok=True)

        # Verify rsync is available locally
        if shutil.which("rsync") is None:
            raise RuntimeError("rsync is not available on the local system")

        # Build ssh command used by rsync (-e)
        ssh_parts = ["ssh", "-p", str(self._conn_port)]
        if self._conn_key_filename:
            ssh_parts += ["-i", self._conn_key_filename]
        
        # Add extra SSH options from environment variable if set
        # This allows CI environments or users to specify additional SSH options
        extra_ssh_options = os.environ.get('SSHDOL_SYNC_TO_EXTRA_SSH_OPTIONS')
        if extra_ssh_options:
            # Split the string into individual options, handling quoted arguments properly
            ssh_parts += shlex.split(extra_ssh_options)
        ssh_cmd_str = " ".join(shlex.quote(p) for p in ssh_parts)

        # Build rsync args
        rsync_cmd: List[str] = ["rsync", "-a"]
        if compress:
            rsync_cmd.append("-z")
        rsync_cmd += ["-e", ssh_cmd_str]

        # Map delete timing flags
        delete_flag_map = {
            "before": "--delete-before",
            "after": "--delete-after",
            "delay": "--delete-delay",
            "during": "--delete-during",
        }

        # Determine deletion behavior
        if delete_mode == "recycle":
            # Recycle implies deletion plus backup to recycle bin dir
            rsync_cmd.append("--delete")
            # Choose default recycle bin dir if not provided
            if not recycle_bin:
                if sys.platform == "darwin":
                    recycle_bin = os.path.expanduser("~/.Trash")
                elif sys.platform.startswith("linux"):
                    recycle_bin = os.path.expanduser("~/.local/share/Trash/files")
                else:
                    recycle_bin = os.path.expanduser("~/.Trash")
            os.makedirs(recycle_bin, exist_ok=True)
            rsync_cmd += ["--backup", f"--backup-dir={recycle_bin}"]
        elif delete_local_files_not_in_remote:
            rsync_cmd.append("--delete")
            if delete_mode:
                if delete_mode not in delete_flag_map:
                    raise ValueError(
                        f"Invalid delete_mode: {delete_mode}. Valid: {list(delete_flag_map.keys()) + ['recycle']}"
                    )
                rsync_cmd.append(delete_flag_map[delete_mode])

        # Allow caller-supplied extra args before operands
        if extra_args:
            rsync_cmd.extend(extra_args)

        # Source and destination (operands at the end)
        # Ensure trailing slash to copy contents of rootdir into target directory
        remote_src = f"{self._conn_user}@{self._conn_host}:{self.rootdir.rstrip('/')}/"
        local_dst = os.path.join(target, "")
        rsync_cmd += [remote_src, local_dst]

        # Execute
        try:
            proc = subprocess.run(
                rsync_cmd,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"rsync failed with code {e.returncode}:\nSTDOUT:\n{e.stdout}\nSTDERR:\n{e.stderr}"
            )


# Default encoding for text files (which can be edited in place to change SshTextFiles default encoding)
DFLT_ENCODING_FOR_TEXT_FILES = "utf-8"


# Convenience classes for text files, to avoid having to specify the encoding in
# SshFiles to get a text file interface
class SshTextFilesReader(SshFilesReader):
    """
    Read-only interface to text files on a remote SSH server.
    """

    __default_encoding = DFLT_ENCODING_FOR_TEXT_FILES


class SshTextFiles(SshFiles):
    """
    Read-write interface to text files on a remote SSH server.
    """

    __default_encoding = DFLT_ENCODING_FOR_TEXT_FILES
