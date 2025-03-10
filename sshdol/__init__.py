"""
SSH-based file access with Mapping interface.

Provides read-only (SshFilesReader) and read-write (SshFiles) implementations
for accessing remote files over SSH.
"""

# TODO: Skip the doctests for now, as they require a live SSH connection
# TODO: Remove encoding parameter (will encode values from outside the class)
# TODO: Make reads recursive when keys are with/multiple/slashes (corresponds to store[with][multiple][slashes])
# TODO: Make possibility of recursive writes (store[with][multiple][slashes] = value) (controlled by an integer parameter defining the levels of recursion)
# TODO: Add a recursive_levels parameter for __iter__ and __len__ and __contains__ to control the depth of recursion

import os
import stat
import paramiko
from pathlib import Path
from typing import Mapping, MutableMapping, Iterator, Any, Optional


def get_ssh_config_for_host(host):
    """
    Get SSH configuration for a specific host from the SSH config file.
    
    Args:
        host: The host alias to look up
        
    Returns:
        dict: Dictionary with SSH configuration parameters
    """
    ssh_config_path = os.path.expanduser('~/.ssh/config')

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

    def __init__(
        self,
        host=None,
        user=None,
        password=None,
        url=None,
        port=22,
        key_filename=None,
        rootdir='.',
        encoding='utf8',
        include_hidden=False,
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
            encoding: Text encoding for file contents
            include_hidden: Whether to include hidden files in iterations
        """
        # Store initialization parameters
        self._init_params = {
            'host': host,
            'user': user,
            'password': password,
            'url': url,
            'port': port,
            'key_filename': key_filename,
            'encoding': encoding,
            'include_hidden': include_hidden,
        }

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
        self._encoding = encoding
        self._include_hidden = include_hidden

        # Change to root directory if it's not the default
        if rootdir != '.':
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
            if self._rootdir == '.':
                new_rootdir = path
            else:
                new_rootdir = (
                    f'{self._rootdir}/{path}'
                    if not self._rootdir.endswith('/')
                    else f'{self._rootdir}{path}'
                )

            # Create a completely new connection for the subdirectory
            new_instance = type(self)(**params, rootdir=new_rootdir)
            return new_instance

        # If it's a file, return its contents
        try:
            with self._sftp.file(path, 'r') as f:
                return f.read().decode(self._encoding)
        except Exception as e:
            raise KeyError(f'Error reading file {k}: {str(e)}')

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
                    yield f'{entry}/'
                else:
                    yield entry
        except Exception as e:
            print(f'Warning: Error listing directory: {e}')

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
            self._sftp.close()
            self._ssh.close()
        except:
            pass

    def __repr__(self):
        """String representation of the object"""
        if 'host' in self._init_params and self._init_params['host']:
            return f"{self.__class__.__name__}(host='{self._init_params['host']}', rootdir='{self._rootdir}')"
        return f"{self.__class__.__name__}(rootdir='{self._rootdir}')"


class SshFiles(SshFilesReader, MutableMapping):
    """
    Read-write interface to files on a remote SSH server.
    
    Examples:
        # Connect and write a file
        >>> s = SshFiles(host="myserver")    # doctest: +SKIP
        >>> s["example.txt"] = "Hello, world!"    # doctest: +SKIP
        >>> print(s["example.txt"])    # doctest: +SKIP
        Hello, world!
    """

    def __setitem__(self, k, v):
        """Write content to a remote file"""
        # Don't allow writing to directories
        if k.endswith('/'):
            raise KeyError(f'Cannot write to a directory: {k}')

        try:
            with self._sftp.file(k, 'w') as f:
                f.write(str(v).encode(self._encoding))
        except Exception as e:
            raise KeyError(f'Error writing to file {k}: {str(e)}')

    def __delitem__(self, k):
        """Delete a file from the remote server"""
        if not k:
            raise KeyError('Cannot delete empty key')

        # Handle directory deletion (trailing slash)
        path = k[:-1] if k.endswith('/') else k

        try:
            if self._is_dir(path):
                # Check if directory is empty
                if self._sftp.listdir(path):
                    raise KeyError(f'Cannot remove non-empty directory: {path}')
                self._sftp.rmdir(path)
            else:
                self._sftp.remove(path)
        except Exception as e:
            raise KeyError(f'Error removing {k}: {str(e)}')

    def mkdir(self, dirpath):
        """
        Create a directory on the remote server
        
        Args:
            dirpath: Path of the directory to create
            
        Returns:
            SshFiles: A new instance for the created directory
        """
        # Remove trailing slash if present
        path = dirpath[:-1] if dirpath.endswith('/') else dirpath

        try:
            self._sftp.mkdir(path)
            # Return a new instance for the created directory
            return self[path]
        except Exception as e:
            raise KeyError(f'Error creating directory {path}: {str(e)}')


# For backward compatibility
SshPersister = SshFiles
