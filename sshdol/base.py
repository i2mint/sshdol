"""Base funcionality for sshdol"""

# TODO: Make reads recursive when keys are with/multiple/slashes (corresponds to store[with][multiple][slashes])
# TODO: Make possibility of recursive writes (store[with][multiple][slashes] = value) (controlled by an integer parameter defining the levels of recursion)
# TODO: Add a recursive_levels parameter for __iter__ and __len__ and __contains__ to control the depth of recursion
from pathlib import Path
from typing import Mapping, MutableMapping, Iterator, Any, Optional
import os
import stat
import paramiko


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


class SshFilesReader(Mapping):
    """
    Read-only interface to files on a remote SSH server.

    Examples:
        # Connect using an SSH config alias
        >>> s = SshFilesReader(host="myserver")  # doctest: +SKIP

        # Connect with explicit parameters
        >>> s = SshFilesReader(user="username", url="example.com")  # doctest: +SKIP
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
        """
        # Store initialization parameters
        self._init_params = {
            'host': host,
            'user': user,
            'password': password,
            'url': url,
            'port': port,
            'key_filename': key_filename,
            'include_hidden': include_hidden,
            'encoding': encoding,
        }

        # Store encoding
        self._encoding = encoding or self.__default_encoding
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
            user = user or ssh_config.get('user')
            url = url or ssh_config.get('hostname')
            port = port if port != 22 else int(ssh_config.get('port', 22))

            # Try to use identity file from config if no key specified
            if not key_filename and 'identityfile' in ssh_config:
                key_filename = ssh_config['identityfile'][0]

        # Expand key filename if provided
        if key_filename:
            key_filename = os.path.expanduser(key_filename)

        # Default identity files if nothing specified
        if not password and not key_filename:
            for default_key in ['~/.ssh/id_rsa', '~/.ssh/id_ed25519']:
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

    def __getitem__(self, k):
        """
        Get contents of a file or return a new instance for directories.
        """
        # Strip trailing slash if present
        path = k[:-1] if k.endswith('/') else k

        # Check if this is a directory
        if self._is_dir(path):
            # Create a new instance for this subdirectory
            params = self._init_params.copy()
            # Create new path by joining current rootdir with the key
            if self._rootdir == ".":
                new_rootdir = path
            else:
                new_rootdir = (
                    f"{self._rootdir}/{path}"
                    if not self._rootdir.endswith('/')
                    else f"{self._rootdir}{path}"
                )

            # Create a completely new connection for the subdirectory
            new_instance = type(self)(**params, rootdir=new_rootdir)
            return new_instance

        # If it's a file, return its contents
        try:
            with self._sftp.file(path, 'rb') as f:
                content = f.read()
                # If encoding is specified, decode the bytes to string
                if self._encoding is not None:
                    content = content.decode(self._encoding)
                return content
        except Exception as e:
            raise KeyError(f"Error reading file {k}: {str(e)}")

    def __iter__(self):
        """Iterate over files and subdirectories in the current directory"""
        try:
            entries = self._sftp.listdir('.')

            # Filter hidden files if needed
            if not self._include_hidden:
                entries = [e for e in entries if not e.startswith('.')]

            # Yield entries, adding slash to directories
            for entry in entries:
                if self._is_dir(entry):
                    yield f"{entry}/"
                else:
                    yield entry
        except Exception as e:
            print(f"Warning: Error listing directory: {e}")

    def __len__(self):
        """Return the number of entries in the current directory"""
        try:
            entries = self._sftp.listdir('.')
            if not self._include_hidden:
                entries = [e for e in entries if not e.startswith('.')]
            return len(entries)
        except Exception:
            return 0

    def __contains__(self, k):
        """Check if a file or directory exists"""
        path = k[:-1] if k.endswith('/') else k
        try:
            self._sftp.stat(path)
            return True
        except IOError:
            return False

    def __del__(self):
        """Close the SSH connection when the object is deleted"""
        try:
            if hasattr(self, '_sftp'):
                self._sftp.close()
            if hasattr(self, '_ssh'):
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
    """

    def __setitem__(self, k, v):
        """Write data to a file on the SSH server"""
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

        # Strip trailing slash if present
        path = k[:-1] if k.endswith('/') else k

        try:
            with self._sftp.file(path, 'wb') as f:
                f.write(v)
        except Exception as e:
            raise KeyError(f"Error writing to file {k}: {str(e)}")

    def __delitem__(self, k):
        """Delete a file on the SSH server"""
        # Strip trailing slash if present
        path = k[:-1] if k.endswith('/') else k

        if not self.__contains__(k):
            raise KeyError(k)

        try:
            self._sftp.remove(path)
        except Exception as e:
            raise KeyError(f"Error deleting file {k}: {str(e)}")


# Default encoding for text files (which can be edited in place to change SshTextFiles default encoding)
DFLT_ENCODING_FOR_TEXT_FILES = 'utf-8'


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
