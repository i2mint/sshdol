# sshdol - SSH File Access Library
SSH file access library providing a Python dict-like interface to remote files, built on dol (Data Object Layer) and paramiko.

**ALWAYS follow these instructions exactly and only fallback to additional search and context gathering if the information in these instructions is incomplete or found to be in error.**

Always reference these instructions first and fallback to search or bash commands only when you encounter unexpected information that does not match the info here.

## Working Effectively
- Bootstrap and install the development environment:
  - `pip install -e .` -- takes 30 seconds to install in development mode
  - `pip install pytest pylint black sphinx sphinx_rtd_theme myst-parser epythet` -- takes 60 seconds to install development dependencies. NEVER CANCEL.
- Build validation:
  - `python -c "import sshdol; print('Import successful')"` -- validates basic installation
- Run tests:
  - `python -m pytest sshdol/tests/ -v` -- takes 5-10 seconds but requires SSH server access. Tests WILL FAIL without proper SSH setup.
  - SSH server configuration required: uses sshdol_server host with sshdol_ci user and SSH key authentication
- Code quality checks:
  - `python -m black --check sshdol --diff` -- takes 5 seconds. Shows formatting issues.
  - `python -m black sshdol` -- applies formatting fixes
  - `python -m pylint sshdol --exit-zero` -- takes 10 seconds. NEVER CANCEL.
- Documentation:
  - `cd docsrc && make html` -- takes 20 seconds. NEVER CANCEL. Builds Sphinx documentation.

## Validation
- Always test basic import and API after making code changes: `python -c "from sshdol.base import SshFiles, SshTextFiles; print('API import successful')"`
- For SSH-dependent features, you can validate the class structure and method signatures without actual SSH connections
- ALWAYS run formatting and linting before submitting changes: `python -m black sshdol && python -m pylint sshdol --exit-zero`
- The test suite requires SSH server access which may not be available in development environments - tests will fail with "No authentication methods available" without proper SSH setup
- Validate rsync availability for sync functionality: `which rsync` (should be present on most Unix systems)
- ALWAYS test a complete validation scenario after making changes (see example below)

## Common tasks

### Repository Structure
```
sshdol/
├── sshdol/                 # Main package directory
│   ├── __init__.py        # Package initialization
│   ├── base.py            # Core SshFiles and SshTextFiles classes
│   └── tests/             # Test suite
│       ├── test_base.py           # Main test file
│       ├── utils_for_testing.py   # Test utilities
│       └── default_test_config.json # Test configuration
├── docsrc/                # Sphinx documentation source
│   ├── conf.py           # Sphinx configuration
│   ├── Makefile          # Documentation build commands
│   └── index.rst         # Documentation main page
├── setup.py              # Standard Python setup
├── setup.cfg             # Package configuration and dependencies
├── README.md             # Main documentation and examples
└── .github/workflows/ci.yml # CI pipeline configuration
```

### Key Classes and Methods
**SshFiles (binary mode)**:
- `SshFiles(host="server", rootdir="/path", create_dirs=True)` -- binary file access
- `s['file.txt'] = b'content'` -- write binary content
- `content = s['file.txt']` -- read binary content
- `'file.txt' in s` -- check file existence
- `list(s)` -- list files and directories
- `s.sync_to("/local/path")` -- fast rsync-based sync

**SshTextFiles (text mode)**:
- `SshTextFiles(host="server", encoding="utf-8")` -- text file access with automatic encoding
- `t['file.txt'] = 'text content'` -- write text content
- `text = t['file.txt']` -- read text content

### Critical Dependencies
- **paramiko**: SSH client library (handles SSH connections and SFTP)
- **py2store**: Provides the mapping/storage interface patterns
- **rsync**: Required for fast sync operations (usually pre-installed on Unix systems)

### Build Times and Timeouts (MEASURED VALUES)
- **Installation**: 30 seconds for `pip install -e .`, 60 seconds with dev dependencies -- NEVER CANCEL: set timeout to 120+ seconds
- **Testing**: 0.5 seconds for test execution (fails without SSH) -- NEVER CANCEL: set timeout to 30+ seconds  
- **Linting**: 5 seconds for `pylint` execution -- NEVER CANCEL: set timeout to 30+ seconds
- **Formatting**: 1-2 seconds for `black` check/apply -- NEVER CANCEL: set timeout to 15+ seconds
- **Documentation**: 15 seconds for `make html` -- NEVER CANCEL: set timeout to 60+ seconds

### SSH Configuration Notes
- Tests use SSH server: `sshdol_server` (164.92.79.155) with user `sshdol_ci`
- SSH key authentication required for testing
- Test directory: `/home/sshdol_ci/sshdol_ci_tests`
- Without SSH access, focus on code structure validation and syntax checking

### Example Validation Scenarios
Test these scenarios after making changes to ensure everything works correctly:

**Basic API Validation** (works without SSH):
```python
# Import and method validation
from sshdol.base import SshFiles, SshTextFiles
print("Classes imported successfully")

# Method signature validation
methods = [m for m in dir(SshFiles) if not m.startswith('_')]
key_methods = ['get', 'items', 'keys', 'sync_to', 'mkdir']
for method in key_methods:
    assert method in methods, f"Missing method: {method}"
print("All key methods available")

# Dependency validation
import shutil, paramiko
assert shutil.which('rsync') is not None, "rsync not available"
print("All dependencies available")
```

**Full Development Validation** (copy-paste friendly):
```bash
cd /path/to/sshdol && python -c "
from sshdol.base import SshFiles, SshTextFiles
import shutil, paramiko
methods = [m for m in dir(SshFiles) if not m.startswith('_')]
key_methods = ['get', 'items', 'keys', 'sync_to', 'mkdir']
assert all(m in methods for m in key_methods), 'Missing methods'
assert shutil.which('rsync') is not None, 'rsync missing'
print('✓ All validation checks passed')
"
```

### CI Pipeline
The GitHub Actions CI pipeline (`.github/workflows/ci.yml`):
- Uses Python 3.10
- Runs formatting with black
- Runs pylint validation
- Runs pytest (with SSH access)
- Publishes to PyPI on master branch
- Builds and publishes documentation

Always ensure your changes pass local formatting and linting before pushing, as the CI will fail otherwise.