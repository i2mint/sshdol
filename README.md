# sshdol

A Python dict-like interface to SSH files, built on [dol](https://github.com/i2mint/dol) (Data Object Layer).


## What is sshdol?

`sshdol` provides a familiar mapping (dict-like) interface to interact with files on remote servers via SSH. Instead of dealing with low-level SSH operations, you can interact with remote files just like you would with Python dictionaries:

```python
s['file.txt'] = b'content'   # Write to a file
content = s['file.txt']      # Read from a file
'file.txt' in s              # Check if file exists
list(s)                      # List all files and directories
```

## Why use sshdol?

`dol` helps create key-value facades to data sources and systems that have Python builtin interfaces. This offers a consistent, easy, and familiar interface to various systems, making it healthier for your code and your developer sanity.

## Installation

```bash
pip install sshdol
```

## Quick Start

To use `sshdol`, you need access to an SSH server and appropriate credentials.

```python
from sshdol.base import SshFiles, SshTextFiles

# Connect to a server (several authentication methods supported)
s = SshFiles(host="myserver", rootdir="/path/to/safe/directory")

# Write binary data to a file
s['example.bin'] = b'binary content'

# Read the file
content = s['example.bin']  # Returns b'binary content'

# List files and directories
files = list(s)  # Returns [..., 'example.bin', ...]

# Check if a file exists
if 'example.bin' in s:
    print("File exists!")
```

## Features

### Binary and Text Mode

`sshdol` provides both binary and text interfaces:

```python
# Binary mode (default)
s = SshFiles(host="myserver", rootdir="/path/to/directory")
s['file.txt'] = b'binary content'

# Text mode
t = SshTextFiles(host="myserver", rootdir="/path/to/directory")
t['file.txt'] = 'text content'  # Automatically handles encoding/decoding
```

### Recursive Directory Support

Navigate through directories and access nested files with slash-separated paths:

```python
# Create a store with unlimited depth and directory creation
s = SshFiles(
    host="myserver",
    rootdir="/path/to/directory",
    max_levels=None,  # Unlimited recursion for listing
    create_dirs=True  # Create directories as needed
)

# Write to a deeply nested path (creates directories if they don't exist)
s['dir1/dir2/dir3/file.txt'] = b'nested content'

# Read from the nested path
content = s['dir1/dir2/dir3/file.txt']  # Returns b'nested content'

# List will show all files and directories recursively
all_files = list(s)  # [..., 'dir1/', 'dir1/dir2/', 'dir1/dir2/dir3/', 'dir1/dir2/dir3/file.txt', ...]
```

### Directory Navigation

Navigate through directories by accessing folders like dictionary keys:

```python
# Get a store instance for a subdirectory
subdir = s['dir1/']

# List only files in the subdirectory
subdir_files = list(subdir)  # [..., 'dir2/', ...]

# Navigate further
subsubdir = subdir['dir2/']
```

### Recursion Control

Control the depth of directory recursion:

```python
# Only show top-level files and directories
s0 = SshFiles(host="myserver", max_levels=0)
files_level0 = list(s0)  # [..., 'dir1/', 'file.txt', ...]

# Show files up to one level deep
s1 = SshFiles(host="myserver", max_levels=1)
files_level1 = list(s1)  # [..., 'dir1/', 'dir1/file.txt', 'dir1/dir2/', ...]
```

### Directory Creation

Automatically create directories when writing to nested paths:

```python
# Create directories as needed when writing
s = SshFiles(host="myserver", create_dirs=True)

# This will create all necessary directories
s['new/path/to/file.txt'] = b'content with auto-created directories'
```

## Authentication Options

`sshdol` supports multiple SSH authentication methods:

```python
# Using SSH config alias (simplest if you have ~/.ssh/config set up)
s = SshFiles(host="myserver")

# Using username/password
s = SshFiles(user="username", password="password", url="example.com")

# Using SSH key
s = SshFiles(user="username", url="example.com", key_filename="~/.ssh/id_rsa")
```

## Advanced Examples

### Working with text files

```python
# Create a text file store
t = SshTextFiles(host="myserver")

# Write a text file
t['notes.txt'] = 'Hello, this is a text note'

# Read it back
text = t['notes.txt']  # Returns 'Hello, this is a text note'
```

### Creating a new directory

```python
# Create a store with directory creation enabled
s = SshFiles(host="myserver", create_dirs=True)

# Create a new directory
projects_dir = s.mkdir('projects')

# Write files in the new directory
projects_dir['README.md'] = b'# Projects Directory'
```

### Handling large directory structures

```python
# Create a store with limited recursion for better performance
s = SshFiles(host="myserver", max_levels=2)

# List files up to 2 levels deep
files = list(s)  # [..., 'dir1/', 'dir1/dir2/', 'dir1/dir2/file.txt', ...]

# You can still access deeper files directly
deep_content = s['dir1/dir2/dir3/dir4/file.txt']
```

## License

MIT
