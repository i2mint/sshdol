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
    # make a bytes files ssh store
    s = SshFiles(host=SSH_TEST_HOST, rootdir=SSH_TEST_ROOTDIR)
    empty_test_store(s)

    assert list(s) == []  # s is empty

    print("Writing b'crumble' to 'apple' file...")
    s['apple'] = b'crumble'  # make an apple file containing b'crumble'
    print("Checking if 'apple' is in the store...")
    assert 'apple' in s  # apple is now in s
    print("Listing the files in the store...")
    assert list(s) == ['apple']  # now, s has only one file, apple
    print("Checking the value of 'apple' is indeed b'crumble'...")
    assert (
        s['apple'] == b'crumble'
    )  # see that the value of s['apple'] is indeed b'crumble'

    # Showing that trying to write a string will fail with
    # TypeError: When encoding is set to 'utf-8', value must be a string
    with pytest.raises(TypeError):
        s['apple'] = 'crumble'

    # But if we want to be reading and writing strings, we can use SshTextFiles
    # which is just a convenience class that sets encoding='utf-8' for us.
    # Or we can use SshFiles with encoding='utf-8' explicitly set:
    text_s = SshFiles(encoding='utf-8', host=SSH_TEST_HOST, rootdir=SSH_TEST_ROOTDIR)

    text_s['apple.txt'] = 'sauce'  # make an apple file containing 'sauce'
    assert 'apple.txt' in text_s  # apple is now in s
    assert sorted(s) == ['apple', 'apple.txt']  # now, s has only one file, apple
    assert (
        text_s['apple.txt'] == 'sauce'
    )  # see that the value of s['apple'] is indeed 'sauce'
