"""UI operation contracts for asynchronous preview/export workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class OperationToken:
    """Token representing a single async operation instance."""

    kind: str
    operation_id: int


class UiOperationContracts:
    """Track active async operations and reject stale callbacks."""

    def __init__(self) -> None:
        self._preview_counter = 0
        self._export_counter = 0
        self._active_preview: Optional[OperationToken] = None
        self._active_export: Optional[OperationToken] = None
        self._active_preview_file: Optional[Path] = None

    def start_preview(self, file_path: Path) -> OperationToken:
        """Register a new preview operation for a file."""
        self._preview_counter += 1
        token = OperationToken(kind="preview", operation_id=self._preview_counter)
        self._active_preview = token
        self._active_preview_file = file_path
        return token

    def is_preview_active_for(self, file_path: Path) -> bool:
        """Return whether a preview operation is currently active for file_path."""
        return self._active_preview is not None and self._active_preview_file == file_path

    def complete_preview(self, token: OperationToken) -> bool:
        """Mark preview complete if token is active; return False for stale token."""
        if token != self._active_preview:
            return False
        self._active_preview = None
        self._active_preview_file = None
        return True

    def start_export(self) -> OperationToken:
        """Register a new export operation."""
        self._export_counter += 1
        token = OperationToken(kind="export", operation_id=self._export_counter)
        self._active_export = token
        return token

    def complete_export(self, token: OperationToken) -> bool:
        """Mark export complete if token is active; return False for stale token."""
        if token != self._active_export:
            return False
        self._active_export = None
        return True

    @property
    def has_active_preview(self) -> bool:
        """Return whether any preview operation is active."""
        return self._active_preview is not None

    @property
    def has_active_export(self) -> bool:
        """Return whether any export operation is active."""
        return self._active_export is not None
