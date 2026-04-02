"""Widget-level state tests for the desktop UI."""

import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtWidgets import QApplication

from app_service import PreparedDocument, ProcessingOptions, ProcessingResult
from desktop_ui import MainWindow


def _dummy_prepared(input_name: str = "paper.pdf") -> PreparedDocument:
    """Create a minimal prepared document for UI tests."""
    original = Image.new("RGB", (40, 60), color=(255, 0, 0))
    extracted = Image.new("RGB", (40, 60), color=(0, 128, 255))
    return PreparedDocument(
        input_path=Path(input_name),
        processor=object(),
        options=ProcessingOptions(),
        margins_list=[{"left": 0, "top": 0, "right": 0, "bottom": 0}],
        original_images=[original],
        preview_images=[extracted],
        gutter_list=None,
    )


def _dummy_prepared_with_pages(
    input_name: str = "paper.pdf",
    original_pages: int = 3,
    extracted_pages: int = 2,
) -> PreparedDocument:
    """Create a prepared document with configurable original/extracted page counts."""
    original_images = [Image.new("RGB", (40, 60), color=(255, 0, 0)) for _ in range(original_pages)]
    extracted_images = [Image.new("RGB", (40, 60), color=(0, 128, 255)) for _ in range(extracted_pages)]
    return PreparedDocument(
        input_path=Path(input_name),
        processor=object(),
        options=ProcessingOptions(),
        margins_list=[{"left": 0, "top": 0, "right": 0, "bottom": 0}] * max(original_pages, 1),
        original_images=original_images,
        preview_images=extracted_images,
        gutter_list=None,
    )


class DesktopUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()

    def tearDown(self):
        self.window.thread_pool.clear()
        self.window.thread_pool.waitForDone(2000)
        self.window.close()

    def test_buttons_follow_busy_contract(self):
        self.window.selected_files = [Path("a.pdf")]
        self.window._update_file_tree()

        self.window._set_busy(False)
        self.assertTrue(self.window.export_button.isEnabled())
        self.assertTrue(self.window.extract_all_button.isEnabled())

        self.window._set_busy(True)
        self.assertFalse(self.window.export_button.isEnabled())
        self.assertFalse(self.window.extract_all_button.isEnabled())

    def test_stale_preview_completion_is_ignored(self):
        stale_file = Path("stale.pdf")
        active_file = Path("active.pdf")
        stale_token = self.window.contracts.start_preview(stale_file)
        self.window.contracts.start_preview(active_file)

        self.window.prepared_document = None
        self.window._preview_ready(stale_token, _dummy_prepared("stale.pdf"))

        self.assertIsNone(self.window.prepared_document)

    def test_export_completion_switches_toggle_to_extracted(self):
        self.window.selected_files = [Path("paper.pdf")]
        self.window._set_busy(True)
        self.window.prepared_document = _dummy_prepared("paper.pdf")
        self.window.preview_toggle.setChecked(False)

        token = self.window.contracts.start_export()
        result = ProcessingResult(pdf_path=Path("paper_cropped.pdf"), exported_reader_files={})
        self.window._export_finished(token, result)

        self.assertTrue(self.window.preview_toggle.isChecked())
        self.assertTrue(self.window.export_button.isEnabled())
        self.assertTrue(self.window.extract_all_button.isEnabled())

    def test_preview_toggle_changes_active_image_source(self):
        prepared = _dummy_prepared("paper.pdf")
        self.window.prepared_document = prepared

        self.window._set_preview_mode(extracted=False)
        self.assertFalse(self.window._showing_extracted_preview())
        self.assertEqual(self.window._active_images(), prepared.original_images)

        self.window._set_preview_mode(extracted=True)
        self.assertTrue(self.window._showing_extracted_preview())
        self.assertEqual(self.window._active_images(), prepared.preview_images)

    def test_status_updates_drive_page_progress(self):
        self.window.batch_export_token = None
        self.window._handle_status_update("Detecting margins: page 7/42")

        self.assertEqual(self.window.progress_bar.maximum(), 42)
        self.assertEqual(self.window.progress_bar.value(), 7)
        self.assertEqual(self.window.progress_label.text(), "Page 7/42")

    def test_batch_status_updates_include_current_file_context(self):
        self.window.batch_export_token = self.window.contracts.start_export()
        self.window._handle_status_update("[paper.pdf] Writing PDF: page 3/10")

        self.assertEqual(self.window.progress_bar.maximum(), 10)
        self.assertEqual(self.window.progress_bar.value(), 3)
        self.assertEqual(self.window.progress_label.text(), "paper.pdf - Page 3/10")

    def test_selecting_new_file_clears_stale_extracted_preview(self):
        self.window.selected_files = [Path("first.pdf"), Path("second.pdf")]
        self.window._update_file_tree()
        self.window.export_running = True

        self.window.prepared_document = _dummy_prepared("first.pdf")
        self.window.preview_toggle.setChecked(True)

        second_item = self.window.file_tree.topLevelItem(1)
        self.window.file_tree.clearSelection()
        second_item.setSelected(True)
        self.window._on_file_selected()

        self.assertFalse(self.window.preview_toggle.isChecked())
        if self.window.prepared_document is not None:
            self.assertEqual(self.window.prepared_document.input_path, Path("second.pdf"))

    def test_selecting_new_file_resets_toggle_even_without_prepared_document(self):
        self.window.selected_files = [Path("first.pdf"), Path("second.pdf")]
        self.window._update_file_tree()
        self.window.export_running = True

        # Simulate stale extracted mode while no prepared doc is cached.
        self.window.prepared_document = None
        self.window.preview_toggle.setChecked(True)

        second_item = self.window.file_tree.topLevelItem(1)
        self.window.file_tree.clearSelection()
        second_item.setSelected(True)
        self.window._on_file_selected()

        self.assertFalse(self.window.preview_toggle.isChecked())

    def test_returning_to_processed_file_restores_cached_preview_for_extracted_view(self):
        first = Path("first.pdf")
        second = Path("second.pdf")
        self.window.selected_files = [first, second]
        self.window._update_file_tree()

        first_prepared = _dummy_prepared("first.pdf")
        second_prepared = _dummy_prepared("second.pdf")
        preview_signature = self.window._build_preview_signature(self.window._options())
        self.window.preview_cache[first] = (preview_signature, first_prepared)
        self.window.preview_cache[second] = (preview_signature, second_prepared)

        # Simulate post-extract mode on first file, then switch to another file.
        self.window.current_file_index = 0
        self.window.prepared_document = first_prepared
        self.window._set_preview_mode(extracted=True)

        self.window.file_tree.clearSelection()
        self.window.file_tree.topLevelItem(1).setSelected(True)
        self.window._on_file_selected()
        self.assertEqual(self.window.current_file_index, 1)
        self.assertEqual(self.window.prepared_document.input_path, second)
        self.assertFalse(self.window.preview_toggle.isChecked())

        # Return to first file and ensure extracted mode can be shown again.
        self.window.file_tree.clearSelection()
        self.window.file_tree.topLevelItem(0).setSelected(True)
        self.window._on_file_selected()
        self.assertEqual(self.window.current_file_index, 0)
        self.assertEqual(self.window.prepared_document.input_path, first)

        self.window._set_preview_mode(extracted=True)
        self.assertEqual(self.window._active_images(), first_prepared.preview_images)

    def test_post_extraction_navigation_in_extracted_mode(self):
        self.window.prepared_document = _dummy_prepared_with_pages(
            "paper.pdf", original_pages=4, extracted_pages=3
        )
        self.window._set_preview_mode(extracted=True)

        self.assertEqual(self.window.current_preview_index, 0)
        self.window._show_next_page()
        self.assertEqual(self.window.current_preview_index, 1)
        self.window._show_next_page()
        self.assertEqual(self.window.current_preview_index, 2)

        # Boundary: cannot move beyond last extracted page.
        self.window._show_next_page()
        self.assertEqual(self.window.current_preview_index, 2)

        self.window._show_previous_page()
        self.assertEqual(self.window.current_preview_index, 1)

    def test_mode_switch_resets_out_of_range_index(self):
        self.window.prepared_document = _dummy_prepared_with_pages(
            "paper.pdf", original_pages=5, extracted_pages=2
        )
        self.window.current_preview_index = 4

        # Switching to extracted mode must reset to a valid index.
        self.window._set_preview_mode(extracted=True)
        self.assertEqual(self.window.current_preview_index, 0)
        self.assertEqual(self.window._active_page_count(), 2)

    def test_previous_boundary_does_not_underflow(self):
        self.window.prepared_document = _dummy_prepared_with_pages(
            "paper.pdf", original_pages=2, extracted_pages=2
        )
        self.window._set_preview_mode(extracted=True)
        self.assertEqual(self.window.current_preview_index, 0)

        self.window._show_previous_page()
        self.assertEqual(self.window.current_preview_index, 0)

    def test_twenty_click_sequences_five_clicks_each_do_not_break_state(self):
        files = [Path("first.pdf"), Path("second.pdf"), Path("third.pdf")]
        self.window.selected_files = files
        self.window.current_file_index = 0
        self.window._update_file_tree()

        # Keep sequence testing deterministic by avoiding async worker startup.
        def _sync_cached_preview_load() -> None:
            current = self.window.selected_files[self.window.current_file_index]
            cached = self.window.preview_cache.get(current)
            if cached is None:
                return
            self.window.prepared_document = cached[1]
            self.window.current_preview_index = 0
            self.window._refresh_preview()

        self.window._auto_load_preview = _sync_cached_preview_load

        signature = self.window._build_preview_signature(self.window._options())
        self.window.preview_cache = {
            files[0]: (signature, _dummy_prepared_with_pages("first.pdf", original_pages=3, extracted_pages=2)),
            files[1]: (signature, _dummy_prepared_with_pages("second.pdf", original_pages=2, extracted_pages=2)),
            files[2]: (signature, _dummy_prepared_with_pages("third.pdf", original_pages=4, extracted_pages=3)),
        }
        self.window.prepared_document = self.window.preview_cache[files[0]][1]
        self.window._refresh_preview()

        def select_index(index: int) -> None:
            self.window.file_tree.clearSelection()
            self.window.file_tree.topLevelItem(index).setSelected(True)
            self.window._on_file_selected()

        actions = {
            "toggle_preview": lambda: self.window.preview_toggle.click(),
            "next_page": lambda: self.window.next_button.click(),
            "prev_page": lambda: self.window.prev_button.click(),
            "toggle_split": lambda: self.window.split_columns_check.click(),
            "toggle_ocr": lambda: self.window.docling_ocr_check.click(),
            "toggle_fallback": lambda: self.window.allow_fallback_check.click(),
            "cycle_detector": lambda: self.window.detector_combo.setCurrentIndex(
                (self.window.detector_combo.currentIndex() + 1)
                % self.window.detector_combo.count()
            ),
            "dpi_up": lambda: self.window.dpi_spin.setValue(
                min(self.window.dpi_spin.maximum(), self.window.dpi_spin.value() + 5)
            ),
            "dpi_down": lambda: self.window.dpi_spin.setValue(
                max(self.window.dpi_spin.minimum(), self.window.dpi_spin.value() - 5)
            ),
            "sensitivity_up": lambda: self.window.sensitivity_spin.setValue(
                min(self.window.sensitivity_spin.maximum(), self.window.sensitivity_spin.value() + 3)
            ),
            "sensitivity_down": lambda: self.window.sensitivity_spin.setValue(
                max(self.window.sensitivity_spin.minimum(), self.window.sensitivity_spin.value() - 3)
            ),
            "select_first": lambda: select_index(0),
            "select_second": lambda: select_index(1),
            "select_third": lambda: select_index(2),
        }

        sequences = [
            ["toggle_preview", "next_page", "prev_page", "toggle_split", "select_second"],
            ["toggle_ocr", "cycle_detector", "select_third", "toggle_preview", "prev_page"],
            ["dpi_up", "next_page", "next_page", "toggle_preview", "select_first"],
            ["sensitivity_down", "toggle_fallback", "select_second", "next_page", "prev_page"],
            ["select_third", "toggle_preview", "toggle_preview", "dpi_down", "cycle_detector"],
            ["select_first", "next_page", "next_page", "next_page", "prev_page"],
            ["toggle_split", "toggle_ocr", "toggle_fallback", "select_second", "toggle_preview"],
            ["sensitivity_up", "sensitivity_up", "dpi_up", "select_third", "toggle_preview"],
            ["cycle_detector", "cycle_detector", "select_first", "toggle_preview", "next_page"],
            ["select_second", "prev_page", "toggle_preview", "next_page", "toggle_preview"],
            ["dpi_down", "dpi_down", "sensitivity_down", "select_third", "prev_page"],
            ["toggle_fallback", "toggle_fallback", "toggle_split", "toggle_split", "select_first"],
            ["toggle_ocr", "toggle_preview", "select_second", "toggle_preview", "select_third"],
            ["next_page", "next_page", "next_page", "next_page", "prev_page"],
            ["select_first", "select_second", "select_third", "select_first", "toggle_preview"],
            ["sensitivity_up", "dpi_up", "cycle_detector", "toggle_ocr", "toggle_split"],
            ["select_second", "toggle_preview", "prev_page", "prev_page", "next_page"],
            ["select_third", "dpi_up", "dpi_down", "sensitivity_up", "sensitivity_down"],
            ["toggle_preview", "toggle_preview", "toggle_preview", "select_first", "next_page"],
            ["cycle_detector", "select_second", "cycle_detector", "select_third", "toggle_fallback"],
        ]

        self.assertEqual(len(sequences), 20)
        for seq_index, sequence in enumerate(sequences, start=1):
            self.assertEqual(len(sequence), 5)
            with self.subTest(sequence=seq_index):
                for action_name in sequence:
                    actions[action_name]()

                    # Core invariants: valid file index and page index bounds.
                    self.assertGreaterEqual(self.window.current_file_index, 0)
                    self.assertLess(self.window.current_file_index, len(self.window.selected_files))

                    if self.window.prepared_document is not None:
                        active_count = self.window._active_page_count()
                        if active_count > 0:
                            self.assertGreaterEqual(self.window.current_preview_index, 0)
                            self.assertLess(self.window.current_preview_index, active_count)

    def test_processed_status_persists_when_new_file_added(self):
        first = Path("first.pdf")
        second = Path("second.pdf")
        self.window.selected_files = [first]

        outputs = self.window._current_output_selection()
        output_dir = self.window.output_edit.text().strip() or None
        signature = self.window._build_export_signature(outputs, output_dir)
        self.window._mark_file_processed(first, signature)

        self.window.selected_files.append(second)
        self.window._update_file_tree()

        first_item = self.window.file_tree.topLevelItem(0)
        second_item = self.window.file_tree.topLevelItem(1)
        self.assertEqual(first_item.text(1), "✓ Processed")
        self.assertEqual(second_item.text(1), "")

    def test_extract_all_skips_up_to_date_files(self):
        first = Path("first.pdf")
        second = Path("second.pdf")
        self.window.selected_files = [first, second]

        outputs = self.window._current_output_selection()
        output_dir = self.window.output_edit.text().strip() or None
        signature = self.window._build_export_signature(outputs, output_dir)
        self.window._mark_file_processed(first, signature)

        needing_extract = self.window._files_needing_extract(outputs, output_dir)
        self.assertEqual(needing_extract, [second])

    def test_config_change_invalidates_processed_status(self):
        file_path = Path("paper.pdf")
        self.window.selected_files = [file_path]

        outputs = self.window._current_output_selection()
        output_dir = self.window.output_edit.text().strip() or None
        signature = self.window._build_export_signature(outputs, output_dir)
        self.window._mark_file_processed(file_path, signature)
        self.window._update_file_tree()
        self.assertEqual(self.window.file_tree.topLevelItem(0).text(1), "✓ Processed")

        self.window.dpi_spin.setValue(self.window.dpi_spin.value() + 1)
        self.window._update_file_tree()

        self.assertEqual(self.window.file_tree.topLevelItem(0).text(1), "↻ Re-extract needed")
        updated_outputs = self.window._current_output_selection()
        updated_signature = self.window._build_export_signature(updated_outputs, output_dir)
        self.assertNotEqual(signature, updated_signature)


if __name__ == "__main__":
    unittest.main()
