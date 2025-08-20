"""Utils for testing."""

from importlib.resources import files
import json

# Constants
with open(files("sshdol.tests") / "default_test_config.json") as f:
    default_test_config = json.load(f)

MAX_TEST_KEYS = default_test_config["MAX_TEST_KEYS"]
SSH_TEST_HOST = default_test_config["SSH_TEST_HOST"]
SSH_TEST_ROOTDIR = default_test_config["SSH_TEST_ROOTDIR"]


def _first_n_keys_and_bust_if_more(store, n=MAX_TEST_KEYS):
    """
    A function that returns the first n keys of a store.
    The raison d'être of this function is to not mistakingly empty the wrong store.
    """
    for i, k in enumerate(store.keys()):
        if i >= n:
            raise ValueError(
                f"More than {n} keys in store. First {n} keys are: {list(store.keys())[:n]}"
            )
        yield k


def _is_the_test_folder(store):
    """
    A function that checks if the store is the test folder.
    The raison d'être of this function is to not mistakingly empty the wrong store.
    """
    return store.rootdir == "/home/sshdol_ci/sshdol_ci_tests"


def _keys_as_expected(keys, max_keys=MAX_TEST_KEYS):
    """
    A function that checks if the keys are as expected.
    The raison d'être of this function is to not mistakingly empty the wrong store.
    """
    return len(keys) <= max_keys


def sort_keys_deepest_first(keys):
    """Return keys sorted by deepest path first, then reverse-alphabetically.

    This ensures files in deeper directories are deleted before their parent directories,
    avoiding "directory not empty" errors on stricter filesystems/servers.
    """
    # Sort by depth (count of '/'), deepest first, then reverse-lexicographically
    # so that sibling files come before their parent directory key.
    return sorted(keys, key=lambda k: (k.count("/"), k), reverse=True)


def empty_test_store(
    store, *, store_as_expected=_is_the_test_folder, keys_as_expected=_keys_as_expected
):
    """
    A function that deletes all items of a store, after verifying a condition on the keys.
    The raison d'être of this function is to not mistakingly empty the wrong store.
    """
    # Note: Yes, we could just have one condition on the store (a condition that verifies
    # the store, and also it's keys), but I prefer to have two separate conditions,
    # so that the error message is more informative, and the function is more efficient
    # (don't need to fetch the keys twice)
    if store_as_expected(store):
        # Sort by deepest path first so files/dirs at the bottom are removed before parents.
        keys = sort_keys_deepest_first(_first_n_keys_and_bust_if_more(store))
        if keys_as_expected(keys):
            for k in keys:
                del store[k]
        else:
            raise ValueError(f"Keys are not as expected: {keys}")
    else:
        raise ValueError(f"Store is not as expected: {store}")
