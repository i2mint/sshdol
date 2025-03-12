"""Test base module for sshdol."""

import pytest
from sshdol.base import SshFiles
from sshdol.tests.utils_for_testing import (
    empty_test_store,
    MAX_TEST_KEYS,
    SSH_TEST_ROOTDIR,
    SSH_TEST_HOST,
)


def test_simple_demo():
    store_to_empty = SshFiles(
        host=SSH_TEST_HOST, rootdir=SSH_TEST_ROOTDIR, max_levels=None
    )
    empty_test_store(store_to_empty)

    # make a bytes files ssh store
    s = SshFiles(host=SSH_TEST_HOST, rootdir=SSH_TEST_ROOTDIR)
    assert list(s) == []  # s is empty

    print("Writing b'crumble' to 'apple' file...")
    s["apple"] = b"crumble"  # make an apple file containing b'crumble'
    print("Checking if 'apple' is in the store...")
    assert "apple" in s  # apple is now in s
    print("Listing the files in the store...")
    assert list(s) == ["apple"]  # now, s has only one file, apple
    print("Checking the value of 'apple' is indeed b'crumble'...")
    assert (
        s["apple"] == b"crumble"
    )  # see that the value of s['apple'] is indeed b'crumble'

    # Showing that trying to write a string will fail with
    # TypeError: When encoding is set to 'utf-8', value must be a string
    with pytest.raises(TypeError):
        s["apple"] = "crumble"

    # But if we want to be reading and writing strings, we can use SshTextFiles
    # which is just a convenience class that sets encoding='utf-8' for us.
    # Or we can use SshFiles with encoding='utf-8' explicitly set:
    text_s = SshFiles(encoding="utf-8", host=SSH_TEST_HOST, rootdir=SSH_TEST_ROOTDIR)

    text_s["apple.txt"] = "sauce"  # make an apple file containing 'sauce'
    assert "apple.txt" in text_s  # apple is now in s
    assert sorted(s) == ["apple", "apple.txt"]  # now, s has only one file, apple
    assert (
        text_s["apple.txt"] == "sauce"
    )  # see that the value of s['apple'] is indeed 'sauce'


def test_recursive_functionality():
    """Test recursive file access and directory depth limit enforcement.

    Verifies:
    1. Unlimited recursion (max_levels=None):
       - Writing and reading from deeply nested paths
       - Directory structure creation
       - Recursive directory listing includes all nested items

    2. Limited recursion (max_levels=1):
       - Directory listing limited to specified depth
       - Operations within allowed depth succeed
       - Operations exceeding max depth raise KeyError with clear messages

    3. Root-only access (max_levels=0):
       - Restricts access to only root-level files
       - Attempting to access subdirectories raises appropriate errors

    4. Membership and containment:
       - 'in' operator works properly with unlimited depth
       - 'in' operator respects max_levels restrictions
       - Non-existent paths are correctly identified

    5. Collection behavior:
       - Length operations reflect the recursion depth constraints

    6. Strict containment:
         - 'in' operator raises KeyError when path depth exceeds max_levels

    7. Membership and containment:
        - 'in' operator works properly with unlimited depth
        - 'in' operator respects max_levels restrictions
        - Non-existent paths are correctly identified
    """
    # Create a store with max_levels=None (unlimited) and create_dirs=True
    s = SshFiles(
        host=SSH_TEST_HOST,
        rootdir=SSH_TEST_ROOTDIR,
        max_levels=None,
        create_dirs=True,
    )
    empty_test_store(s)

    # Test recursive write with directory creation (unlimited depth)
    s["level0/level1/level2/file.txt"] = b"deep file content"

    # Test recursive read
    assert s["level0/level1/level2/file.txt"] == b"deep file content"

    # Test recursive iteration (with unlimited depth)
    all_keys = list(s)
    assert "level0/" in all_keys
    assert "level0/level1/" in all_keys
    assert "level0/level1/level2/" in all_keys
    assert "level0/level1/level2/file.txt" in all_keys

    # Test with limited recursion depth
    s_limited = SshFiles(
        host=SSH_TEST_HOST,
        rootdir=SSH_TEST_ROOTDIR,
        max_levels=1,  # Only one level of subdirectories
        create_dirs=True,
    )

    # Should only see first level directories and files
    limited_keys = list(s_limited)
    assert "level0/" in limited_keys
    assert "level0/level1/" in limited_keys
    assert "level0/level1/level2/" not in limited_keys

    # Writing at allowed depth should work
    s_limited["level0/file.txt"] = b"allowed depth content"
    assert s_limited["level0/file.txt"] == b"allowed depth content"

    # Test that reading beyond max_levels raises KeyError with appropriate message
    with pytest.raises(KeyError) as excinfo:
        _ = s_limited["level0/level1/level2/file.txt"]
    assert "Path depth (3) exceeds maximum allowed depth (1)" in str(excinfo.value)

    # Test that writing beyond max_levels raises KeyError with appropriate message
    with pytest.raises(KeyError) as excinfo:
        s_limited["level0/level1/file.txt"] = b"beyond max depth"
    assert "Path depth (2) exceeds maximum allowed depth (1)" in str(excinfo.value)

    # Test with level 0 (only root level)
    s_root_only = SshFiles(
        host=SSH_TEST_HOST,
        rootdir=SSH_TEST_ROOTDIR,
        max_levels=0,
    )

    # Should be able to access files in the root
    root_keys = list(s_root_only)
    assert "level0/" in root_keys
    assert "level0/level1/" not in root_keys

    # Test that accessing even one level deep raises error
    with pytest.raises(KeyError) as excinfo:
        _ = s_root_only["level0/file.txt"]
    assert "Path depth (1) exceeds maximum allowed depth (0)" in str(excinfo.value)

    # Test membership with recursion
    assert "level0/level1/level2/file.txt" in s  # Unlimited depth store
    assert "level0/level1/level2/nonexistent.txt" not in s

    # Test length with recursion
    # Length should include all files and directories up to max_levels
    assert len(s) > len(s_limited)

    # Test membership check also respects max_levels
    assert "level0/level1/file.txt" not in s_limited

    # Test that strict_contains=True will make 'in' operator raise KeyError
    # in case of depth violation
    # See: https://github.com/i2mint/sshdol/issues/1#issuecomment-2714508482
    s_strict = SshFiles(
        host=SSH_TEST_HOST,
        rootdir=SSH_TEST_ROOTDIR,
        max_levels=1,
        strict_contains=True,
    )

    with pytest.raises(KeyError) as excinfo:
        "level0/level1/file.txt" in s_strict  # Will now raise KeyError
    assert "Path depth (2) exceeds maximum allowed depth (1)" in str(excinfo.value)
