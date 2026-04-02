"""Desktop UI for selecting files, previewing pages, and exporting outputs."""

from __future__ import annotations

import io
import os
import re
import traceback
from pathlib import Path
from typing import Callable, Optional

import fitz
from PIL import Image
from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QAction, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app_service import (
    OutputSelection,
    PreparedDocument,
    ProcessingOptions,
    prepare_document,
    process_document,
    resolve_output_selection,
)
from ui_contracts import OperationToken, UiOperationContracts



class TaskSignals(QObject):
    """Signals emitted by background worker tasks."""

    finished = Signal(object)
    failed = Signal(str)
    status = Signal(str)


class WorkerTask(QRunnable):
    """Run a callable in the global Qt thread pool."""

    def __init__(self, fn: Callable[[Callable[[str], None]], object]):
        super().__init__()
        self.fn = fn
        self.signals = TaskSignals()

    def run(self) -> None:
        try:
            result = self.fn(self.signals.status.emit)
        except BaseException:
            self.signals.failed.emit(traceback.format_exc())
            return
        self.signals.finished.emit(result)


class MainWindow(QMainWindow):
    """Main application window with controls and preview."""

    def __init__(self):
        super().__init__()
        self.thread_pool = QThreadPool.globalInstance()
        self.contracts = UiOperationContracts()
        self.prepared_document: Optional[PreparedDocument] = None
        self.export_running = False
        self.preview_running = False
        self.preview_target: Optional[Path] = None
        self.pending_selected_export: Optional[tuple[Path, OutputSelection, Optional[str]]] = None
        self.batch_export_token: Optional[OperationToken] = None
        self.batch_signature: Optional[str] = None
        self.batch_files: list[Path] = []
        self.batch_outputs: Optional[OutputSelection] = None
        self.batch_output_dir: Optional[str] = None
        self.batch_next_file_index = 0
        self.batch_running_count = 0
        self.batch_completed_count = 0
        # Native layout/cropping dependencies can crash under threaded parallel load.
        # Keep a safe default of 1 worker; allow explicit opt-in via env override.
        env_workers = os.getenv("EPUB_PAPERS_BATCH_WORKERS", "1").strip()
        try:
            requested_workers = int(env_workers)
        except ValueError:
            requested_workers = 1
        self.batch_worker_limit = max(1, min(4, requested_workers))
        self.current_preview_index = 0
        self._fitz_page_count: int = 0
        self.selected_files: list[Path] = []
        self.file_processed_signatures: dict[Path, str] = {}
        self.preview_cache: dict[Path, tuple[str, PreparedDocument]] = {}
        self.current_file_index = 0
        self._page_progress_pattern = re.compile(r"page\s+(\d+)\s*/\s*(\d+)", re.IGNORECASE)

        self.setWindowTitle("EPUB Papers")
        self.resize(1600, 900)
        self._build_ui()
        self._refresh_preview()

    def _build_ui(self) -> None:
        """Build the main UI layout."""
        root = QWidget()
        self.setCentralWidget(root)

        # Main horizontal splitter: preview (left) | controls (right)
        main_splitter = QSplitter(Qt.Horizontal)

        # Left panel: preview
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self._build_preview_toolbar())
        left_layout.addWidget(self._build_preview_area(), stretch=1)

        # Right panel: vertical split of controls (top) and file tree (bottom)
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        # Top: controls section
        controls_section = QWidget()
        controls_layout = QVBoxLayout(controls_section)
        controls_layout.setContentsMargins(5, 5, 5, 5)
        controls_layout.addWidget(self._build_option_group())
        controls_layout.addWidget(self._build_progress_group())
        controls_layout.addWidget(self._build_log_group(), stretch=1)
        
        # Bottom: file tree section
        file_tree_section = self._build_file_tree_group()
        
        # Vertical splitter for right panel
        right_splitter = QSplitter(Qt.Vertical)
        right_splitter.addWidget(controls_section)
        right_splitter.addWidget(file_tree_section)
        right_splitter.setSizes([600, 300])
        right_splitter.setStretchFactor(0, 1)
        right_splitter.setStretchFactor(1, 1)
        
        right_layout.addWidget(right_splitter, stretch=1)
        right_layout.addWidget(self._build_sticky_extract_all_bar())

        main_splitter.addWidget(left_panel)
        main_splitter.addWidget(right_panel)
        main_splitter.setSizes([900, 700])

        layout = QHBoxLayout(root)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.addWidget(main_splitter)

        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.close)
        self.menuBar().addAction(quit_action)

    def _build_file_tree_group(self) -> QGroupBox:
        """Build the file tree group showing selected files/folders."""
        group = QGroupBox("Files & Folders")
        layout = QVBoxLayout(group)

        # Buttons for file/folder selection
        button_widget = QWidget()
        button_layout = QHBoxLayout(button_widget)
        button_layout.setContentsMargins(0, 0, 0, 0)

        add_file_btn = QPushButton("Add File(s)")
        add_file_btn.clicked.connect(self._add_files)
        add_folder_btn = QPushButton("Add Folder")
        add_folder_btn.clicked.connect(self._add_folder)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._clear_files)

        button_layout.addWidget(add_file_btn)
        button_layout.addWidget(add_folder_btn)
        button_layout.addWidget(clear_btn)

        output_row = QWidget()
        output_layout = QHBoxLayout(output_row)
        output_layout.setContentsMargins(0, 0, 0, 0)
        self.output_edit = QLineEdit()
        self.output_edit.setText(str(Path.cwd()))
        self.output_edit.textChanged.connect(self._update_file_tree)
        output_browse = QPushButton("Browse")
        output_browse.clicked.connect(self._choose_output_dir)
        output_layout.addWidget(QLabel("Output Folder"))
        output_layout.addWidget(self.output_edit, stretch=1)
        output_layout.addWidget(output_browse)

        # Tree widget to show selected files/folders
        self.file_tree = QTreeWidget()
        self.file_tree.setHeaderLabels(["Path", "Status"])
        self.file_tree.setColumnCount(2)
        self.file_tree.itemSelectionChanged.connect(self._on_file_selected)

        layout.addWidget(button_widget)
        layout.addWidget(output_row)
        layout.addWidget(self.file_tree, stretch=1)
        return group

    def _add_files(self) -> None:
        """Add multiple PDF files to the selection."""
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "Select PDF files", str(Path.cwd()), "PDF Files (*.pdf)"
        )
        for file_path in file_paths:
            path = Path(file_path)
            if path not in self.selected_files:
                self.selected_files.append(path)
        self._update_file_tree()
        self._set_busy(self.export_running)

    def _add_folder(self) -> None:
        """Add all PDFs from a folder to the selection."""
        folder_path = QFileDialog.getExistingDirectory(self, "Select folder containing PDFs", str(Path.cwd()))
        if folder_path:
            folder = Path(folder_path)
            pdf_files = sorted(folder.glob("*.pdf"))
            for pdf_file in pdf_files:
                if pdf_file not in self.selected_files:
                    self.selected_files.append(pdf_file)
            self._update_file_tree()
            self._set_busy(self.export_running)

    def _clear_files(self) -> None:
        """Clear all selected files."""
        self.selected_files.clear()
        self.file_processed_signatures.clear()
        self.preview_cache.clear()
        self.current_file_index = 0
        self.prepared_document = None
        self.current_preview_index = 0
        self._update_file_tree()
        self._set_busy(self.export_running)
        self._refresh_preview()

    def _build_preview_signature(self, options: ProcessingOptions) -> str:
        """Build a stable signature for preview-related processing options."""
        signature = (
            options.sensitivity,
            options.dpi,
            options.detector_mode,
            options.allow_fallback,
            options.docling_ocr,
            options.split_columns,
        )
        return repr(signature)

    def _current_output_selection(self) -> OutputSelection:
        """Get output selection from current UI state without validations."""
        return resolve_output_selection(
            legacy_format="pdf" if self.output_pdf_check.isChecked() else "epub",
            skip_epub=not self.output_epub_check.isChecked(),
            reader_formats=self._reader_formats(),
        )

    def _build_export_signature(self, outputs: OutputSelection, output_dir: Optional[str]) -> str:
        """Build a stable signature for current extraction configuration."""
        options = self._options()
        normalized_output_dir = str(Path(output_dir).expanduser()) if output_dir else ""
        signature = (
            options.sensitivity,
            options.dpi,
            options.detector_mode,
            options.allow_fallback,
            options.docling_ocr,
            options.split_columns,
            outputs.write_pdf,
            tuple(outputs.reader_formats),
            normalized_output_dir,
        )
        return repr(signature)

    def _files_needing_extract(self, outputs: OutputSelection, output_dir: Optional[str]) -> list[Path]:
        """Return files that require extraction for the given configuration."""
        signature = self._build_export_signature(outputs, output_dir)
        return [
            file_path
            for file_path in self.selected_files
            if self.file_processed_signatures.get(file_path) != signature
        ]

    def _mark_file_processed(self, file_path: Path, signature: str) -> None:
        """Record that file_path has been extracted with signature."""
        self.file_processed_signatures[file_path] = signature

    def _update_file_tree(self) -> None:
        """Update the file tree display."""
        outputs = self._current_output_selection()
        output_dir = self.output_edit.text().strip() or None
        current_signature = self._build_export_signature(outputs, output_dir)

        self.file_tree.clear()
        for i, file_path in enumerate(self.selected_files):
            item = QTreeWidgetItem()
            item.setText(0, file_path.name)
            processed_signature = self.file_processed_signatures.get(file_path)
            if processed_signature == current_signature:
                status = "✓ Processed"
            elif processed_signature is not None:
                status = "↻ Re-extract needed"
            else:
                status = ""
            item.setText(1, status)
            if i == self.current_file_index:
                item.setSelected(True)
            self.file_tree.addTopLevelItem(item)

    def _on_file_selected(self) -> None:
        """Handle file selection from the tree."""
        selected_items = self.file_tree.selectedItems()
        if selected_items:
            index = self.file_tree.indexOfTopLevelItem(selected_items[0])
            if index >= 0 and index < len(self.selected_files):
                newly_selected = self.selected_files[index]
                previous_index = self.current_file_index
                self.current_file_index = index

                # Selection contract: a new file starts in original-view context
                # and must not display stale extracted pages from another file.
                if index != previous_index:
                    self.preview_toggle.blockSignals(True)
                    self.preview_toggle.setChecked(False)
                    self.preview_toggle.blockSignals(False)

                if (
                    self.prepared_document is not None
                    and self.prepared_document.input_path != newly_selected
                ):
                    self.prepared_document = None
                    self.current_preview_index = 0
                    self.preview_label.setText(f"Loading: {newly_selected.name}...")
                    self.page_label.setText("Loading preview...")

                # Auto-load preview for selected file
                if not self.export_running:
                    self._auto_load_preview()

    def _auto_load_preview(self) -> None:
        """Automatically load preview for the currently selected file."""
        if self.current_file_index >= len(self.selected_files):
            return

        current_file = self.selected_files[self.current_file_index]
        current_options = self._options()
        preview_signature = self._build_preview_signature(current_options)

        cached = self.preview_cache.get(current_file)
        if cached is not None:
            cached_signature, cached_prepared = cached
            if cached_signature == preview_signature:
                self.prepared_document = cached_prepared
                self.current_preview_index = 0
                self._append_status(f"Loaded cached preview: {current_file.name}")
                self._refresh_preview()
                return

        if self.preview_running and self.preview_target == current_file:
            return
        if self.contracts.is_preview_active_for(current_file):
            return

        self._append_status(f"Loading: {current_file.name}")
        self._show_first_page_immediately(current_file)
        self.prepared_document = None
        self._set_busy(self.export_running)
        self.progress_bar.setVisible(True)
        self.preview_running = True
        self.preview_target = current_file
        token = self.contracts.start_preview(current_file)

        task = WorkerTask(
            lambda status: self._prepare_document_resilient(current_file, current_options, status)
        )
        task.signals.status.connect(self._handle_status_update)
        task.signals.finished.connect(lambda result, token=token: self._preview_ready(token, result))
        task.signals.failed.connect(lambda details, token=token: self._preview_failed(token, details))
        self.thread_pool.start(task)

    def _show_fitz_page(self, pdf_path: Path, page_index: int) -> None:
        """Render a specific page via fitz on the main thread."""
        try:
            dpi = self.dpi_spin.value()
            zoom = dpi / 72.0
            matrix = fitz.Matrix(zoom, zoom)
            doc = fitz.open(str(pdf_path))
            try:
                if len(doc) == 0:
                    return
                self._fitz_page_count = len(doc)
                page_index = max(0, min(page_index, len(doc) - 1))
                pix = doc[page_index].get_pixmap(matrix=matrix)
            finally:
                doc.close()

            if pix.n - pix.alpha < 3:
                rgb_pix = fitz.Pixmap(fitz.csRGB, pix)
                image = Image.frombytes("RGB", [rgb_pix.width, rgb_pix.height], rgb_pix.samples)
            else:
                image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

            self.current_preview_index = page_index
            preview_pixmap = self._pil_to_pixmap(image)
            scaled = preview_pixmap.scaledToWidth(800, Qt.SmoothTransformation)
            self.preview_label.setPixmap(scaled)
            total = self._fitz_page_count
            loading = " / loading..." if self.prepared_document is None else f" / {total}"
            self.page_label.setText(f"Page {page_index + 1}{loading}")
        except Exception:
            self.preview_label.setText("Preparing preview...")

    def _show_first_page_immediately(self, pdf_path: Path) -> None:
        """Render page 1 quickly so the original PDF is visible before extraction finishes."""
        self._fitz_page_count = 0
        self._show_fitz_page(pdf_path, 0)
        self.progress_label.setText("Preparing full preview...")

    def _build_option_group(self) -> QGroupBox:
        """Build a common options card for processing and output types."""
        group = QGroupBox("Options")
        layout = QFormLayout(group)

        self.sensitivity_spin = QSpinBox()
        self.sensitivity_spin.setRange(0, 100)
        self.sensitivity_spin.setValue(90)

        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(72, 300)
        self.dpi_spin.setValue(150)

        self.detector_combo = QComboBox()
        self.detector_combo.addItems(["network", "hybrid", "legacy"])
        self.detector_combo.setCurrentText("hybrid")
        self.detector_combo.currentTextChanged.connect(self._update_file_tree)

        self.allow_fallback_check = QCheckBox("Allow fallback on network failure")
        self.allow_fallback_check.setChecked(True)
        self.split_columns_check = QCheckBox("Split dual-column pages")
        self.docling_ocr_check = QCheckBox("Enable Docling OCR")
        self.allow_fallback_check.toggled.connect(self._update_file_tree)
        self.split_columns_check.toggled.connect(self._update_file_tree)
        self.docling_ocr_check.toggled.connect(self._update_file_tree)

        self.output_pdf_check = QCheckBox("Write cropped PDF")
        self.output_pdf_check.setChecked(True)
        self.output_epub_check = QCheckBox("Write EPUB")
        self.output_epub_check.setChecked(True)
        self.output_cbz_check = QCheckBox("Write CBZ")
        self.output_pdf_check.toggled.connect(self._update_file_tree)
        self.output_epub_check.toggled.connect(self._update_file_tree)
        self.output_cbz_check.toggled.connect(self._update_file_tree)

        self.sensitivity_spin.valueChanged.connect(self._update_file_tree)
        self.dpi_spin.valueChanged.connect(self._update_file_tree)

        output_types_row = QWidget()
        output_types_layout = QHBoxLayout(output_types_row)
        output_types_layout.setContentsMargins(0, 0, 0, 0)
        output_types_layout.addWidget(self.output_pdf_check)
        output_types_layout.addWidget(self.output_epub_check)
        output_types_layout.addWidget(self.output_cbz_check)

        layout.addRow("Sensitivity", self.sensitivity_spin)
        layout.addRow("DPI", self.dpi_spin)
        layout.addRow("Detector Mode", self.detector_combo)
        layout.addRow("Fallback", self.allow_fallback_check)
        layout.addRow("Columns", self.split_columns_check)
        layout.addRow("OCR", self.docling_ocr_check)
        layout.addRow("Outputs", output_types_row)
        return group

    def _build_sticky_extract_all_bar(self) -> QWidget:
        """Build a bottom action bar that keeps Extract All visible."""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(5, 8, 5, 5)

        btn_style = (
            "font-weight: 600; font-size: 13px; "
            "background-color: #22884a; color: white; border-radius: 5px;"
        )

        self.export_button = QPushButton("Extract Selected")
        self.export_button.setMinimumHeight(36)
        self.export_button.setStyleSheet(btn_style)
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._export_current_file)

        self.extract_all_button = QPushButton("Extract All")
        self.extract_all_button.setMinimumHeight(36)
        self.extract_all_button.setStyleSheet(btn_style)
        self.extract_all_button.clicked.connect(self._export_all_files)

        layout.addStretch(1)
        layout.addWidget(self.export_button)
        layout.addWidget(self.extract_all_button)
        return widget

    def _build_progress_group(self) -> QGroupBox:
        """Build the progress indicator group."""
        group = QGroupBox("Progress")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(5, 5, 5, 5)

        self.file_progress_title = QLabel("Current file")
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_label = QLabel("")

        self.batch_progress_title = QLabel("Batch files")
        self.batch_progress_bar = QProgressBar()
        self.batch_progress_bar.setVisible(False)
        self.batch_progress_label = QLabel("")

        layout.addWidget(self.file_progress_title)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.batch_progress_title)
        layout.addWidget(self.batch_progress_bar)
        layout.addWidget(self.batch_progress_label)
        return group

    def _build_log_group(self) -> QGroupBox:
        """Build the status log group."""
        group = QGroupBox("Status")
        layout = QVBoxLayout(group)

        self.status_log = QPlainTextEdit()
        self.status_log.setReadOnly(True)
        layout.addWidget(self.status_log)
        return group

    def _build_preview_toolbar(self) -> QWidget:
        """Build the preview toolbar with navigation controls."""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        toggle_widget = QWidget()
        toggle_layout = QHBoxLayout(toggle_widget)
        toggle_layout.setContentsMargins(0, 0, 0, 0)
        toggle_layout.setSpacing(6)

        self.original_label = QLabel("Original PDF")
        self.extracted_label = QLabel("Extracted PDF")

        self.preview_toggle = QCheckBox()
        self.preview_toggle.setChecked(False)
        self.preview_toggle.stateChanged.connect(self._refresh_preview)
        self.preview_toggle.setStyleSheet(
            "QCheckBox::indicator { width: 42px; height: 24px; border-radius: 12px; "
            "background: #d1d5db; border: 1px solid #9aa4af; }"
            "QCheckBox::indicator:checked { background: #1f8b4c; border: 1px solid #1f8b4c; }"
        )

        toggle_layout.addWidget(self.original_label)
        toggle_layout.addWidget(self.preview_toggle)
        toggle_layout.addWidget(self.extracted_label)

        self.prev_button = QPushButton("Previous")
        self.prev_button.clicked.connect(self._show_previous_page)
        self.next_button = QPushButton("Next")
        self.next_button.clicked.connect(self._show_next_page)

        self.page_label = QLabel("No preview loaded")

        layout.addWidget(toggle_widget)
        layout.addWidget(self.prev_button)
        layout.addWidget(self.next_button)
        layout.addWidget(self.page_label, stretch=1)
        return widget

    def _build_preview_area(self) -> QWidget:
        """Build the preview area for displaying PDF pages."""
        self.preview_label = QLabel("Select a PDF from the left panel to preview.")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(500, 700)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setAlignment(Qt.AlignCenter)
        scroll.setWidget(self.preview_label)
        self.preview_scroll = scroll
        return scroll

    def _choose_output_dir(self) -> None:
        """Choose output directory."""
        dir_path = QFileDialog.getExistingDirectory(
            self, "Select output folder", self.output_edit.text() or str(Path.cwd())
        )
        if dir_path:
            self.output_edit.setText(dir_path)

    def _options(self) -> ProcessingOptions:
        """Build ProcessingOptions from UI controls."""
        return ProcessingOptions(
            sensitivity=self.sensitivity_spin.value(),
            dpi=self.dpi_spin.value(),
            detector_mode=self.detector_combo.currentText(),
            allow_fallback=self.allow_fallback_check.isChecked(),
            docling_ocr=self.docling_ocr_check.isChecked(),
            split_columns=self.split_columns_check.isChecked(),
        )

    def _prepare_document_resilient(
        self,
        file_path: Path,
        options: ProcessingOptions,
        status_fn: Callable[[str], None],
    ) -> PreparedDocument:
        """Prepare a document, retrying once with safer settings on known network-empty failures."""
        try:
            return prepare_document(str(file_path), options, status_fn)
        except RuntimeError as exc:
            msg = str(exc).lower()
            should_retry = (
                options.detector_mode == "network"
                and not options.allow_fallback
                and "network detection returned nothing" in msg
            )
            if not should_retry:
                raise

            status_fn("Network detector returned no layout on a page. Retrying with hybrid + fallback...")
            retry_options = ProcessingOptions(
                sensitivity=options.sensitivity,
                dpi=options.dpi,
                detector_mode="hybrid",
                allow_fallback=True,
                docling_ocr=options.docling_ocr,
                debug_layout_dir=options.debug_layout_dir,
                split_columns=options.split_columns,
            )
            return prepare_document(str(file_path), retry_options, status_fn)

    def _reader_formats(self) -> tuple[str, ...]:
        """Get selected reader output formats."""
        formats: list[str] = []
        if self.output_epub_check.isChecked():
            formats.append("epub")
        if self.output_cbz_check.isChecked():
            formats.append("cbz")
        return tuple(formats)

    def _showing_extracted_preview(self) -> bool:
        """Return whether the extracted PDF preview is currently selected."""
        return self.preview_toggle.isChecked()

    def _set_preview_mode(self, extracted: bool) -> None:
        """Switch the preview toggle between original and extracted PDF."""
        self.preview_toggle.setChecked(extracted)

        # Navigation contract: after mode switches, land on a valid page.
        # Reset to the first page to avoid stale out-of-range indices.
        self.current_preview_index = 0
        self._refresh_preview()

    def _append_status(self, message: str) -> None:
        """Append a message to the status log."""
        self.status_log.appendPlainText(message)

    def _handle_status_update(self, message: str) -> None:
        """Handle task status messages and reflect page progress in UI."""
        self._append_status(message)

        match = self._page_progress_pattern.search(message)
        if not match:
            return

        current = int(match.group(1))
        total = int(match.group(2))
        if total <= 0:
            return

        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(min(current, total))
        self.progress_bar.setVisible(True)
        if message.startswith("[") and "]" in message:
            file_name = message[1 : message.index("]")]
            self.progress_label.setText(f"{file_name} - Page {current}/{total}")
        else:
            self.progress_label.setText(f"Page {current}/{total}")

    def _set_busy(self, busy: bool) -> None:
        """Enable/disable buttons during processing."""
        self.export_running = busy
        has_files = bool(self.selected_files)
        self.extract_all_button.setEnabled(not busy and has_files)
        self.export_button.setEnabled(not busy and has_files)

    def _preview_ready(self, token: OperationToken, prepared_document: PreparedDocument) -> None:
        """Handle preview preparation completion."""
        if not self.contracts.complete_preview(token):
            return

        self.preview_running = False
        self.preview_target = None
        self.prepared_document = prepared_document
        self.preview_cache[prepared_document.input_path] = (
            self._build_preview_signature(prepared_document.options),
            prepared_document,
        )
        self.current_preview_index = 0
        self._append_status(f"✓ Preview ready: {prepared_document.page_count} page(s)")
        self._set_busy(self.export_running)
        self.progress_bar.setVisible(False)
        self.progress_label.setText("")
        self.batch_progress_bar.setVisible(False)
        self.batch_progress_label.setText("")
        self._update_file_tree()
        self._refresh_preview()

        if self.pending_selected_export is not None:
            pending_file, outputs, output_dir = self.pending_selected_export
            if prepared_document.input_path == pending_file:
                self.pending_selected_export = None
                self._append_status(f"Continuing selected export: {pending_file.name}...")
                export_signature = self._build_export_signature(outputs, output_dir)
                self._start_export_task(
                    lambda status: (
                        pending_file,
                        export_signature,
                        process_document(prepared_document, outputs, output_dir, status),
                    )
                )

    def _preview_failed(self, token: OperationToken, details: str) -> None:
        """Handle preview failure for active operation only."""
        if not self.contracts.complete_preview(token):
            return
        self.preview_running = False
        self.preview_target = None
        self.pending_selected_export = None
        self._set_busy(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setVisible(False)
        self.progress_label.setText("")
        self.batch_progress_bar.setVisible(False)
        self.batch_progress_label.setText("")
        self._append_status("✗ Preview failed. See error dialog for details.")
        QMessageBox.critical(self, "Task Failed", details)

    def _export_current_file(self) -> None:
        """Export the currently loaded file."""
        if not self.selected_files:
            QMessageBox.warning(self, "No Files", "Add at least one PDF file first.")
            return

        selected_items = self.file_tree.selectedItems()
        selected_index = self.current_file_index
        if selected_items:
            index = self.file_tree.indexOfTopLevelItem(selected_items[0])
            if 0 <= index < len(self.selected_files):
                selected_index = index

        selected_file = self.selected_files[selected_index]

        outputs = resolve_output_selection(
            legacy_format="pdf" if self.output_pdf_check.isChecked() else "epub",
            skip_epub=not self.output_epub_check.isChecked(),
            reader_formats=self._reader_formats(),
        )
        if not outputs.write_pdf and not outputs.reader_formats:
            QMessageBox.warning(self, "No Outputs Selected", "Choose at least one output type.")
            return

        self._append_status(f"Exporting selected file: {selected_file.name}...")
        self._set_busy(True)
        self.progress_bar.setRange(0, 0)  # indeterminate spinner
        self.progress_bar.setVisible(True)
        output_dir = self.output_edit.text().strip() or None
        export_signature = self._build_export_signature(outputs, output_dir)

        if self.preview_running and self.preview_target == selected_file:
            self.pending_selected_export = (selected_file, outputs, output_dir)
            self._append_status("Preview still running; export will continue automatically when ready...")
            return

        def prepare_and_export_selected(status_fn):
            if (
                self.prepared_document is not None
                and self.prepared_document.input_path == selected_file
            ):
                prepared = self.prepared_document
            else:
                prepared = self._prepare_document_resilient(selected_file, self._options(), status_fn)
            return (selected_file, export_signature, process_document(prepared, outputs, output_dir, status_fn))

        self._start_export_task(prepare_and_export_selected)

    def _start_export_task(self, fn: Callable[[Callable[[str], None]], object]) -> None:
        """Start export task with token contract to reject stale callbacks."""
        token = self.contracts.start_export()
        task = WorkerTask(fn)
        task.signals.status.connect(self._handle_status_update)
        task.signals.finished.connect(lambda result, token=token: self._export_finished(token, result))
        task.signals.failed.connect(lambda details, token=token: self._export_failed(token, details))
        self.thread_pool.start(task)

    def _export_all_files(self) -> None:
        """Export all selected files with bounded parallelism."""
        if not self.selected_files:
            QMessageBox.warning(self, "No Files", "Add files before exporting.")
            return

        outputs = resolve_output_selection(
            legacy_format="pdf" if self.output_pdf_check.isChecked() else "epub",
            skip_epub=not self.output_epub_check.isChecked(),
            reader_formats=self._reader_formats(),
        )
        if not outputs.write_pdf and not outputs.reader_formats:
            QMessageBox.warning(self, "No Outputs Selected", "Choose at least one output type.")
            return

        output_dir = self.output_edit.text().strip() or None
        files_to_process = self._files_needing_extract(outputs, output_dir)
        if not files_to_process:
            self._append_status("✓ All selected files are already processed for current settings.")
            return

        skipped_count = len(self.selected_files) - len(files_to_process)
        worker_count = min(self.batch_worker_limit, len(files_to_process))
        self._append_status(
            f"Starting batch export of {len(files_to_process)} file(s) with {worker_count} worker(s)..."
        )
        if skipped_count > 0:
            self._append_status(f"Skipping {skipped_count} up-to-date file(s).")
        self._set_busy(True)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(True)
        self.progress_label.setText("Waiting for page progress...")

        self.batch_progress_bar.setVisible(True)
        self.batch_progress_bar.setRange(0, len(files_to_process))
        self.batch_progress_bar.setValue(0)
        self.batch_progress_label.setText(f"0/{len(files_to_process)} files")
        self.batch_export_token = self.contracts.start_export()
        self.batch_signature = self._build_export_signature(outputs, output_dir)
        self.batch_files = files_to_process
        self.batch_outputs = outputs
        self.batch_output_dir = output_dir
        self.batch_next_file_index = 0
        self.batch_running_count = 0
        self.batch_completed_count = 0

        self._start_more_batch_workers(self.batch_export_token)

    def _start_more_batch_workers(self, token: OperationToken) -> None:
        """Launch additional batch workers up to configured parallelism."""
        if token != self.batch_export_token:
            return

        if self.batch_outputs is None:
            return

        outputs = self.batch_outputs
        output_dir = self.batch_output_dir
        worker_limit = min(self.batch_worker_limit, len(self.batch_files))

        while (
            self.batch_running_count < worker_limit
            and self.batch_next_file_index < len(self.batch_files)
        ):
            file_index = self.batch_next_file_index
            self.batch_next_file_index += 1
            self.batch_running_count += 1
            self._start_batch_file_worker(token, outputs, output_dir, file_index)

    def _start_batch_file_worker(
        self,
        token: OperationToken,
        outputs: OutputSelection,
        output_dir: Optional[str],
        file_index: int,
    ) -> None:
        """Start a worker for a single batch file index."""
        current_file = self.batch_files[file_index]
        self._append_status(f"Batch [{file_index + 1}/{len(self.batch_files)}] Processing: {current_file.name}")

        def prepare_and_export_file(status_fn):
            def scoped_status(msg: str) -> None:
                status_fn(f"[{current_file.name}] {msg}")

            prepared = self._prepare_document_resilient(current_file, self._options(), scoped_status)
            result = process_document(prepared, outputs, output_dir, scoped_status)
            return (current_file, result)

        task = WorkerTask(prepare_and_export_file)
        task.signals.finished.connect(
            lambda result, token=token: self._batch_file_exported(token, result)
        )
        task.signals.failed.connect(lambda details, token=token: self._export_failed(token, details))
        self.thread_pool.start(task)

    def _batch_file_exported(self, token: OperationToken, result) -> None:
        """Handle completion of a single file in batch export."""
        if token != self.batch_export_token:
            return

        self.batch_running_count = max(0, self.batch_running_count - 1)
        self.batch_completed_count += 1
        self.batch_progress_bar.setValue(self.batch_completed_count)
        self.batch_progress_label.setText(f"{self.batch_completed_count}/{len(self.batch_files)} files")

        file_path, _export_result = result
        if self.batch_signature is not None:
            self._mark_file_processed(file_path, self.batch_signature)
            self._update_file_tree()

        if self.batch_completed_count >= len(self.batch_files):
            self.contracts.complete_export(token)
            self.batch_export_token = None
            self.batch_signature = None
            self.batch_files = []
            self.batch_outputs = None
            self.batch_output_dir = None
            self._append_status("✓ Batch export complete!")
            self._set_busy(False)
            self.progress_bar.setVisible(False)
            self.progress_label.setText("")
            self.batch_progress_bar.setVisible(False)
            self.batch_progress_label.setText("")
            QMessageBox.information(self, "Batch Export Complete", "All files have been processed.")
            return

        self._start_more_batch_workers(token)

    def _export_finished(self, token: OperationToken, result) -> None:
        """Handle export completion."""
        if not self.contracts.complete_export(token):
            return

        if isinstance(result, tuple) and len(result) == 3:
            file_path, export_signature, export_result = result
        else:
            # Backward-compatible path for direct ProcessingResult inputs.
            export_result = result
            if 0 <= self.current_file_index < len(self.selected_files):
                file_path = self.selected_files[self.current_file_index]
            elif self.prepared_document is not None:
                file_path = self.prepared_document.input_path
            else:
                file_path = Path("unknown.pdf")
            outputs = self._current_output_selection()
            output_dir = self.output_edit.text().strip() or None
            export_signature = self._build_export_signature(outputs, output_dir)

        self._mark_file_processed(file_path, export_signature)
        self._update_file_tree()

        if export_result.pdf_path is not None:
            self._append_status(f"✓ Saved PDF: {export_result.pdf_path}")
        for fmt_name, path in export_result.exported_reader_files.items():
            self._append_status(f"✓ Saved {fmt_name.upper()}: {path}")

        # After extraction, show extracted output in preview by default.
        self._set_preview_mode(extracted=True)

        self._append_status("✓ Export complete.")
        self._set_busy(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setVisible(False)
        self.progress_label.setText("")
        self.batch_progress_bar.setVisible(False)
        self.batch_progress_label.setText("")

    def _export_failed(self, token: OperationToken, details: str) -> None:
        """Handle export task failure for active operation only."""
        if not self.contracts.complete_export(token):
            return
        self.batch_export_token = None
        self.batch_signature = None
        self.batch_files = []
        self.batch_outputs = None
        self.batch_output_dir = None
        self.batch_running_count = 0
        self.batch_next_file_index = 0
        self.batch_completed_count = 0
        self._set_busy(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setVisible(False)
        self.progress_label.setText("")
        self.batch_progress_bar.setVisible(False)
        self.batch_progress_label.setText("")
        self._append_status("✗ Export failed. See error dialog for details.")
        QMessageBox.critical(self, "Task Failed", details)

    def _show_previous_page(self) -> None:
        """Show previous preview page."""
        if self.current_preview_index <= 0:
            return
        if self.prepared_document is None:
            # Navigate via fitz while background task is running
            if self.current_file_index < len(self.selected_files):
                self._show_fitz_page(self.selected_files[self.current_file_index], self.current_preview_index - 1)
            return
        self.current_preview_index -= 1
        self._refresh_preview()

    def _show_next_page(self) -> None:
        """Show next preview page."""
        if self.prepared_document is None:
            # Navigate via fitz while background task is running
            if self.current_file_index < len(self.selected_files) and self._fitz_page_count > 0:
                if self.current_preview_index < self._fitz_page_count - 1:
                    self._show_fitz_page(self.selected_files[self.current_file_index], self.current_preview_index + 1)
            return
        max_index = self._active_page_count() - 1
        if self.current_preview_index < max_index:
            self.current_preview_index += 1
            self._refresh_preview()

    def _active_page_count(self) -> int:
        """Get page count for current preview mode."""
        if self.prepared_document is None:
            return 0
        if self._showing_extracted_preview():
            return self.prepared_document.page_count
        else:
            return len(self.prepared_document.original_images)

    def _active_images(self) -> list[Image.Image]:
        """Get active image list based on preview mode."""
        if self.prepared_document is None:
            return []
        if self._showing_extracted_preview():
            return self.prepared_document.preview_images
        else:
            return self.prepared_document.original_images

    def _pil_to_pixmap(self, pil_image: Image.Image) -> QPixmap:
        """Convert PIL Image to QPixmap via PNG buffer."""
        buffer = io.BytesIO()
        pil_image.save(buffer, format="PNG")
        buffer.seek(0)
        pixmap = QPixmap()
        pixmap.loadFromData(buffer.getvalue(), "PNG")
        return pixmap

    def _refresh_preview(self) -> None:
        """Refresh the preview display."""
        if self.prepared_document is None:
            self.preview_label.setText("Select a PDF from the left panel to preview.")
            self.page_label.setText("No preview loaded")
            return

        images = self._active_images()
        if not images or self.current_preview_index >= len(images):
            self.preview_label.setText("No images available.")
            self.page_label.setText("No pages")
            return

        pil_image = images[self.current_preview_index]
        pixmap = self._pil_to_pixmap(pil_image)

        # Scale to fit in the preview area while maintaining aspect ratio
        max_width = 800
        max_height = 700
        scaled = pixmap.scaled(
            max_width,
            max_height,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )

        self.preview_label.setPixmap(scaled)
        self.page_label.setText(f"Page {self.current_preview_index + 1} of {len(images)}")


def main() -> int:
    """Entry point for the desktop application."""
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

