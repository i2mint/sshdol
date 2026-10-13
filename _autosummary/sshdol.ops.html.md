# sshdol.ops

Key-taking and scope-wide operations, as free functions over the caller’s (possibly wrapped) store.

`dol` wraps stores by delegation, so a *method* of a wrapped `SshFiles` runs bound to the
inner leaf and receives the caller’s **outer**, unmapped key (i2mint/sshdol#6, i2mint/dol#83).
Under a key codec `mkdir` created the directory in the wrong place, and `sync_to` (which
is scoped by `rootdir`, not by any key view) copied files the view hides and, with
`--delete`, pruned the wrong local tree. A free function is handed the outer store itself,
so it can resolve the key through every wrapping layer before touching the server.

- [`mkdir()`](#sshdol.ops.mkdir) `(store, path)` maps `path` through every layer (`inner_most_key`).
- [`sync_to()`](#sshdol.ops.sync_to) `(store, target, subdir=...)` takes the *bare* store only: rsync cannot
  honour a key view, so a wrapped store (or a wrapped `target`) is refused with
  [`WrappedStoreError`](sshdol.base.html.md#sshdol.base.WrappedStoreError). State the scope explicitly with `subdir=`.

The same design as cosmodol.ops and s3dol’s ADR-0011. The `SshFiles.mkdir` /
`SshFiles.sync_to` methods were removed (they raise an `AttributeError` naming the
replacement): a method cannot reliably tell it is wrapped, a free function is handed the
caller’s own store.

```pycon
>>> from sshdol.ops import mkdir, sync_to
>>> view = KeyCodecs.prefixed("sub/")(SshFiles(host="myserver"))
>>> mkdir(view, "newdir")  # creates rootdir/sub/newdir
```

What stays outside the reach of [`mkdir()`](#sshdol.ops.mkdir), stated rather than hidden: a `filt_iter`
scope is not consulted before a directory is created (there is no non-writing scope probe
for a key that does not exist yet), so the directory can be created outside the view.

### Functions

| [`mkdir`](#sshdol.ops.mkdir)(store, path, \*[, exist_ok])   | Create directory `path` (a key of `store`) on the server.              |
|---------------------------------------------------------------------------------------|------------------------------------------------------------------------|
| [`sync_to`](#sshdol.ops.sync_to)(store, target, \*[, subdir]) | Rsync `store`'s remote tree (or its `subdir`) into the local `target`. |

### sshdol.ops.mkdir(store, path, , exist_ok=False)

Create directory `path` (a key of `store`) on the server.

`path` is resolved through every layer of `store` first, so it lands where
`store[path] = ...` would write. Returns nothing: index `store[path]` yourself for
the sub-store (a value codec may not be able to decode a directory).

* **Parameters:**
  * **store** – an `SshFiles`, wrapped or not
  * **path** – a key of `store`
  * **exist_ok** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – if True, an existing directory is not an error
* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### sshdol.ops.sync_to(store, target, , subdir=None, \*\*kwargs)

Rsync `store`’s remote tree (or its `subdir`) into the local `target`.

`store` must be bare: an rsync is scoped by `rootdir`, which no key view can narrow,
so a wrapped `store` (or wrapped `target`) raises `WrappedStoreError`. To sync one
subdirectory, say so with `subdir` (a path relative to `rootdir`). Other keyword
arguments are those of `SshFiles.sync_to`’s implementation: `delete_local_files_not_in_remote`,
`delete_mode`, `recycle_bin`, `compress`, `extra_args`.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)
