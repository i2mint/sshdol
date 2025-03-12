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
from typing import Mapping, MutableMapping, Iterator, Any, Optional, List, Tuple, Union
import os
import stat
import paramiko
from functools import lru_cache

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
        # Connect using an SSH config alias
        >>> s = SshFilesReader(host="myserver")  # doctest: +SKIP

        # Connect with explicit parameters
        >>> s = SshFilesReader(user="username", url="example.com")  # doctest: +SKIP

        # Access nested files with path-based keys
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
            "encoding": encoding,
            "max_levels": max_levels,
            "create_dirs": create_dirs,
            "strict_contains": strict_contains,
        }

        # Store encoding
        self._encoding = encoding or self.__default_encoding
        assert self._encoding is None or isinstance(
            self._encoding, str
        ), "Encoding must be a string"

        # Store recursion parameters
        self._max_levels = max_levels
        self._create_dirs = create_dirs
        self._strict_contains = strict_contains

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
        self._rootdir = rootdir
        self._include_hidden = include_hidden

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
        """Check if a path exists"""
        try:
            self._sftp.stat(path)
            return True
        except IOError:
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
        Recursively walk a directory and yield entries with their paths.

        Args:
            path: Current directory path
            current_level: Current recursion level
            max_levels: Maximum recursion depth (None for unlimited)

        Yields:
            tuple: (path, is_dir) for each entry
        """
        if max_levels is not None and current_level > max_levels:
            return

        try:
            entries = self._list_directory(path)

            for entry in entries:
                entry_path = f"{path}/{entry}" if path != "." else entry
                is_dir = self._is_dir(entry_path)

                # Yield the current entry
                yield entry_path, is_dir

                # If it's a directory and we're not at max depth, recurse
                if is_dir and (max_levels is None or current_level < max_levels):
                    yield from self._walk_directory(
                        entry_path, current_level + 1, max_levels
                    )
        except Exception as e:
            print(f"Warning: Error walking directory {path}: {e}")

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

        # If the key contains slashes, it might be a nested path
        if "/" in path:
            dir_part, file_part = split_path(path)

            # Check if directory part exists
            if dir_part and not self._path_exists(dir_part):
                raise KeyError(f"Directory part does not exist: {dir_part}")

            # Check if the whole path is a directory
            if self._is_dir(path):
                # Create a new instance for this subdirectory
                params = self._init_params.copy()

                # Create new path by joining current rootdir with the key
                if self._rootdir == ".":
                    new_rootdir = path
                else:
                    new_rootdir = (
                        f"{self._rootdir}/{path}"
                        if not self._rootdir.endswith("/")
                        else f"{self._rootdir}{path}"
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
        if self._is_dir(path):
            # Create a new instance for this subdirectory
            params = self._init_params.copy()

            # Create new path by joining current rootdir with the key
            if self._rootdir == ".":
                new_rootdir = path
            else:
                new_rootdir = (
                    f"{self._rootdir}/{path}"
                    if not self._rootdir.endswith("/")
                    else f"{self._rootdir}{path}"
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
        """
        # Use the current object's max_levels
        max_levels = self._max_levels

        if max_levels == 0:
            # If max_levels is 0, just list the current directory
            entries = self._list_directory(".")
            for entry in entries:
                if self._is_dir(entry):
                    yield f"{entry}/"
                else:
                    yield entry
        else:
            # For recursive listing, use _walk_directory
            seen = set()  # To prevent duplicates
            for path, is_dir in self._walk_directory(".", 0, max_levels):
                # Skip the current directory (.)
                if path == ".":
                    continue

                # Add a trailing slash to directories
                if is_dir:
                    path = f"{path}/"

                if path not in seen:
                    seen.add(path)
                    yield path

    def __len__(self):
        """
        Return the number of entries up to max_levels deep.
        """
        count = 0
        for _ in self:
            count += 1
        return count

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

        # For direct contains check, we can just check existence
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
        return f"{self.__class__.__name__}(rootdir='{self._rootdir}')"


class SshFiles(SshFilesReader, MutableMapping):
    """
    Read-write interface to files on a remote SSH server.

    Example:
        >>> s = SshFiles(host="myserver")  # doctest: +SKIP
        >>> s['file.txt'] = b'Hello, world!'  # doctest: +SKIP
        >>> s = SshFiles(host="myserver", encoding="utf-8")  # doctest: +SKIP
        >>> s['file.txt'] = 'Hello, world!'  # doctest: +SKIP

        # Write to nested paths with directory creation
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
