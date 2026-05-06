from __future__ import annotations

from typing import Iterable


def select_input_files(
    files: Iterable[tuple[str, str]],
    manifest: dict,
    explicit_files: list[str] | None,
) -> list[tuple[str, str]]:
    """Choose which (path, sha256) pairs to process.

    - If ``explicit_files`` is non-empty, return only entries whose path is in
      that list (order preserved from ``files``).
    - Otherwise return entries whose hash is not listed in
      ``manifest["seen_hashes"]``.
    """
    rows = list(files)
    if explicit_files:
        allow = set(explicit_files)
        return [f for f in rows if f[0] in allow]
    seen = set(manifest.get("seen_hashes", []))
    return [f for f in rows if f[1] not in seen]
