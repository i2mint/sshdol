"""Key-taking and scope-wide operations, as free functions over the caller's (possibly wrapped) store.

``dol`` wraps stores by delegation, so a *method* of a wrapped ``SshFiles`` runs bound to the
inner leaf and receives the caller's **outer**, unmapped key (i2mint/sshdol#6, i2mint/dol#83).
Under a key codec ``mkdir`` created the directory in the wrong place, and ``sync_to`` (which
is scoped by ``rootdir``, not by any key view) copied files the view hides and, with
``--delete``, pruned the wrong local tree. A free function is handed the outer store itself,
so it can resolve the key through every wrapping layer before touching the server.

- :func:`mkdir` ``(store, path)`` maps ``path`` through every layer (``inner_most_key``)
  and returns ``store[path]``, i.e. the caller's wrapped view of the new directory.
- :func:`sync_to` ``(store, target, subdir=...)`` takes the *bare* store only: rsync cannot
  honour a key view, so a wrapped store (or a wrapped ``target``) is refused with
  :class:`~sshdol.base.WrappedStoreError`. State the scope explicitly with ``subdir=``.

The same design as cosmodol.ops and s3dol's ADR-0011. The ``SshFiles.mkdir`` /
``SshFiles.sync_to`` methods remain for bare stores and refuse when they detect a wrapper.

>>> from sshdol.ops import mkdir, sync_to  # doctest: +SKIP
>>> view = KeyCodecs.prefixed("sub/")(SshFiles(host="myserver"))  # doctest: +SKIP
>>> mkdir(view, "newdir")  # creates rootdir/sub/newdir  # doctest: +SKIP

What stays outside the reach of :func:`mkdir`, stated rather than hidden: a ``filt_iter``
scope is not consulted before a directory is created (there is no non-writing scope probe
for a key that does not exist yet), so the directory can be created outside the view.
"""

from __future__ import annotations

from dol import inner_most_key

from sshdol.base import (
    SshFiles,
    SshFilesReader,
    WrappedStoreError,
    _refuse_if_wrapped,
    _resolve_sync_target,
)


def _leaf_of(store) -> SshFilesReader:
    """The innermost ``SshFilesReader`` under any number of ``dol`` wrappers."""
    cur, seen = store, set()
    while not isinstance(cur, SshFilesReader):
        inner = getattr(cur, "store", None)
        if inner is None or id(cur) in seen:
            raise TypeError(f"{type(store).__name__} does not wrap an sshdol store")
        seen.add(id(cur))
        cur = inner
    return cur


def mkdir(store, path, *, exist_ok: bool = False):
    """Create directory ``path`` (a key of ``store``) on the server; return ``store[path]``.

    ``path`` is resolved through every layer of ``store`` first, so it lands where
    ``store[path] = ...`` would write.

    :param store: an ``SshFiles``, wrapped or not
    :param path: a key of ``store``
    :param exist_ok: if True, an existing directory is not an error
    """
    leaf = _leaf_of(store)
    if not isinstance(leaf, SshFiles):
        raise TypeError("mkdir needs a writable SshFiles, got a reader")
    inner = inner_most_key(store, path, default=None)
    if not isinstance(inner, str):
        inner = path  # no layer maps keys: the key is already a leaf key
    leaf._mkdir_path(inner, exist_ok=exist_ok)
    return store[path]


def sync_to(store, target, *, subdir: str | None = None, **kwargs) -> None:
    """Rsync ``store``'s remote tree (or its ``subdir``) into the local ``target``.

    ``store`` must be bare: an rsync is scoped by ``rootdir``, which no key view can narrow,
    so a wrapped ``store`` (or wrapped ``target``) raises ``WrappedStoreError``. To sync one
    subdirectory, say so with ``subdir`` (a path relative to ``rootdir``). Other keyword
    arguments are those of ``SshFiles.sync_to``'s implementation: ``delete_local_files_not_in_remote``,
    ``delete_mode``, ``recycle_bin``, ``compress``, ``extra_args``.
    """
    _refuse_if_wrapped(store, "sync_to", "the unwrapped store (with subdir=)")
    if not isinstance(store, SshFilesReader):
        raise TypeError(f"Expected an SshFilesReader, got {type(store).__name__}")
    store._sync_to(_resolve_sync_target(target), subdir=subdir, **kwargs)
