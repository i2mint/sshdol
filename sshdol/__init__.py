"""
SSH-based file access with Mapping interface.

Provides read-only (SshFilesReader) and read-write (SshFiles) implementations
for accessing remote files over SSH.

|        | read-only          | read-write         |
| :----- | :----------------- | :----------------- |
| bytes  | SshFilesReader     | SshFiles           |
| text   | SshTextFilesReader | SshTextFiles       |
"""

from sshdol.base import (
    SshFilesReader,  # Read-only interface to files on a remote SSH server.
    SshFiles,  # Read-write interface to files on a remote SSH server.
    SshTextFilesReader,  # Read-only interface to text files on a remote SSH server.
    SshTextFiles,  # Read-write interface to text files on a remote SSH server.
)
