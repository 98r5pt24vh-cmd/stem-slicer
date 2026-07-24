import os
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("STEM_SLICER_DISABLE_ENGINE_AUTOSTART", "1")

from PySide6.QtCore import QMimeData, QPoint, QPointF, QRect, QSize, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QFontMetrics
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QLabel
from PySide6.QtMultimedia import QMediaPlayer

from app import DropZone, KeyEngineLoader, LayerCard, LineIcon, MainWindow, QuickExtractManagerDialog, WaveformWidget
from filename_templates import TOKENS
from theme import application_stylesheet
from widgets import TokenStrip
from storage import StorageManager
from validated_ui import ORANGE, PURPLE, RED
from stem_workflow import QuickExtractWorkflowWorker
import validated_ui


APP = QApplication.instance() or QApplication([])


class MemorySettings:
    def __init__(self, root):
        self.values = {"storage/root": root}

    def value(self, key, default="", type=None):
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value


class QtInterfaceTests(unittest.TestCase):
    @staticmethod
    def global_rect(widget):
        top_left = widget.mapToGlobal(QPoint(0, 0))
        bottom_right = widget.mapToGlobal(QPoint(widget.width(), widget.height()))
        return QRect(top_left, bottom_right).normalized()

    @staticmethod
    def click_through_graphics_view(window, widget):
        """Reproduce a real click entering through the scaled QGraphicsView."""
        canvas_point = widget.mapTo(window.canvas, widget.rect().center())
        scene_point = window.proxy.mapToScene(QPointF(canvas_point))
        viewport_point = window.view.mapFromScene(scene_point)
        QTest.mouseClick(window.view.viewport(), Qt.LeftButton, pos=viewport_point)
        APP.processEvents()

    def test_key_engine_loader_warms_model_before_ready(self):
        events = []

        class FakeAnalyzer:
            def __init__(self, workers=1):
                events.append(("created", workers))

            def start(self):
                events.append(("started",))

            def analyze(self, path, **kwargs):
                events.append(("warmed", os.path.basename(path), kwargs.get("bpm_mode")))
                return {"camelot": "9A"}

        loader = KeyEngineLoader()
        loader.ready.connect(lambda analyzer: events.append(("ready", analyzer.__class__.__name__)))
        with patch("functional_core.KeyAnalyzer", FakeAnalyzer):
            loader.run()
        APP.processEvents()

        self.assertIn(("warmed", "key-and-bpm-engine-warmup.wav", "quick_scan_loop"), events)
        self.assertIn(("ready", "FakeAnalyzer"), events)
        self.assertLess(
            events.index(("warmed", "key-and-bpm-engine-warmup.wav", "quick_scan_loop")),
            events.index(("ready", "FakeAnalyzer")),
        )

    def test_main_pages_are_stable_and_navigable(self):
        window = MainWindow()
        window.show()
        APP.processEvents()

        self.assertEqual(window.pages.count(), 2)
        self.assertEqual(window.pages.currentIndex(), 0)
        self.assertTrue(window.stem_tab.active)
        self.assertFalse(window.quick_tab.active)
        self.assertEqual((window.width(), window.height()), (1024, 691))
        self.assertEqual(window.minimumSize(), QSize(1024, 691))
        self.assertEqual(window.maximumSize(), QSize(1024, 691))
        self.assertEqual(
            [window.scale_select.itemText(index) for index in range(window.scale_select.count())],
            ["100%", "110%", "120%", "130%", "140%", "150%"],
        )

        window.scale_select.setCurrentText("150%")
        APP.processEvents()
        self.assertEqual((window.width(), window.height()), (1536, 1036))
        self.assertEqual(window.minimumSize(), QSize(1536, 1036))
        self.assertEqual(window.maximumSize(), QSize(1536, 1036))
        window.scale_select.setCurrentText("100%")

        original_pages = tuple(window.pages.widget(index) for index in range(2))
        QTest.mouseClick(window.quick_tab, Qt.LeftButton)
        APP.processEvents()
        self.assertEqual(window.pages.currentIndex(), 1)
        self.assertFalse(window.stem_tab.active)
        self.assertTrue(window.quick_tab.active)

        QTest.mouseClick(window.stem_tab, Qt.LeftButton)
        APP.processEvents()
        self.assertEqual(window.pages.currentIndex(), 0)
        self.assertEqual(original_pages, tuple(window.pages.widget(index) for index in range(2)))
        window.close()

    def test_custom_tabs_toggles_and_headers_receive_real_viewport_clicks(self):
        window = MainWindow()
        window.show()
        APP.processEvents()

        self.click_through_graphics_view(window, window.quick_tab)
        self.assertEqual(window.pages.currentIndex(), 1)
        self.click_through_graphics_view(window, window.stem_tab)
        self.assertEqual(window.pages.currentIndex(), 0)

        self.assertTrue(window.layer_switch.isChecked())
        self.click_through_graphics_view(window, window.layer_switch)
        self.assertFalse(window.layer_switch.isChecked())

        self.assertTrue(window.key_switch.isChecked())
        self.click_through_graphics_view(window, window.key_operation_card.header)
        self.assertFalse(window.key_switch.isChecked())
        self.assertFalse(window.key_panel.isVisible())

        self.assertFalse(window.convert_switch.isChecked())
        self.click_through_graphics_view(window, window.target_operation_card.header)
        self.assertTrue(window.convert_switch.isChecked())
        self.assertTrue(window.target_panel.isVisible())
        window.close()

    def test_quick_controls_receive_real_viewport_clicks_at_scaled_size(self):
        window = MainWindow()
        window.show()
        APP.processEvents()
        self.click_through_graphics_view(window, window.quick_tab)

        self.assertFalse(window.quick_extract_bpm_switch.isChecked())
        self.click_through_graphics_view(window, window.quick_extract_bpm_switch)
        self.assertTrue(window.quick_extract_bpm_switch.isChecked())
        self.assertTrue(window.quick_extract_bpm.isEnabled())

        self.assertTrue(window.quick_convert_key_switch.isChecked())
        self.click_through_graphics_view(window, window.quick_convert_key_switch)
        self.assertFalse(window.quick_convert_key_switch.isChecked())
        self.assertFalse(window.quick_convert_key.isEnabled())

        self.click_through_graphics_view(window, window.quick_minor_button)
        self.assertEqual(window.quick_degree_reference, "minor")
        self.click_through_graphics_view(window, window.quick_flats_button)
        self.assertEqual(window.quick_accidentals, "flats")

        window.scale_select.setCurrentText("150%")
        APP.processEvents()
        self.click_through_graphics_view(window, window.stem_tab)
        self.assertEqual(window.pages.currentIndex(), 0)
        window.close()

    def test_destination_buttons_receive_real_viewport_clicks_when_available(self):
        window = MainWindow()
        window.key_engine_state = "ready"
        window.layer_switch.setChecked(False)
        window.convert_switch.setChecked(False)
        window.key_switch.setChecked(True)
        window._sync_stem_state()
        window.show()
        APP.processEvents()

        self.assertTrue(window.rename_destination_button.isEnabled())
        self.click_through_graphics_view(window, window.rename_destination_button)
        self.assertEqual(window.destination_mode, "rename_in_place")
        self.assertTrue(window.rename_destination_button.property("active"))
        self.assertFalse(window.copy_destination_button.property("active"))

        self.click_through_graphics_view(window, window.copy_destination_button)
        self.assertEqual(window.destination_mode, "copy_to_output")
        window.close()

    def test_scale_menu_is_explicit_hoverable_and_never_overlaps_selector(self):
        window = MainWindow()
        window.show()
        APP.processEvents()

        self.assertEqual(
            [window.scale_select.itemText(index) for index in range(window.scale_select.count())],
            ["100%", "110%", "120%", "130%", "140%", "150%"],
        )
        window.scale_select.setCurrentText("130%")
        APP.processEvents()
        self.assertEqual(window.scale_select.currentText(), "130%")
        self.assertTrue(window.scale_select._actions[130].isChecked())

        window.scale_select._show_menu()
        APP.processEvents()
        menu_rect = window.scale_select._menu.geometry()
        selector_top = window.scale_select.mapToGlobal(window.scale_select.rect().topLeft()).y()
        selector_bottom = window.scale_select.mapToGlobal(window.scale_select.rect().bottomLeft()).y()
        self.assertTrue(menu_rect.top() > selector_bottom or menu_rect.bottom() < selector_top)
        selector_left = window.scale_select.mapToGlobal(QPoint(0, 0)).x()
        selector_right = window.scale_select.mapToGlobal(QPoint(window.scale_select.width(), 0)).x()
        self.assertGreaterEqual(menu_rect.width(), abs(selector_right - selector_left))
        selected = window.scale_select._actions[130]
        check_center = selected.check_label.mapToGlobal(selected.check_label.rect().center()).y()
        text_center = selected.text_label.mapToGlobal(selected.text_label.rect().center()).y()
        self.assertLessEqual(abs(check_center - text_center), 1)
        window.scale_select._menu.hide()
        window.close()

    def test_quick_target_fields_are_readable_and_never_clipped(self):
        window = MainWindow()
        window.show()
        APP.processEvents()
        window.select_tab(1)
        APP.processEvents()

        for percent in (100, 110, 120, 130, 140, 150):
            window.scale_select.setCurrentText(f"{percent}%")
            APP.processEvents()
            for field in (
                window.quick_extract_bpm,
                window.quick_extract_key,
                window.quick_convert_bpm,
                window.quick_convert_key,
            ):
                parent = field.parentWidget()
                self.assertTrue(parent.rect().contains(field.geometry()))
                self.assertGreaterEqual(
                    parent.contentsRect().right() - field.geometry().right(),
                    3,
                )
        window.scale_select.setCurrentText("100%")
        APP.processEvents()

        key_metrics = QFontMetrics(window.quick_extract_key.font())
        self.assertLessEqual(
            key_metrics.horizontalAdvance(window.quick_extract_key.currentText()),
            window.quick_extract_key.width() - 28,
        )
        for selector in (
            window.quick_extract_key,
            window.quick_convert_key,
            window.target_key_combo,
        ):
            metrics = QFontMetrics(selector.font())
            for index in range(selector.count()):
                self.assertLessEqual(
                    metrics.horizontalAdvance(selector.itemText(index)),
                    selector.width() - 28,
                )
        self.assertEqual(window.quick_extract_bpm.height(), 18)
        self.assertEqual(window.quick_extract_key.height(), 18)
        self.assertEqual(window.quick_convert_bpm.size(), QSize(48, 18))
        self.assertEqual(window.quick_convert_key.height(), 18)
        self.assertEqual(window.target_bpm_input.height(), window.target_key_combo.height())
        self.assertEqual(window.target_bpm_input.height(), 29)

        # All controls share one explicit vertical axis.  This guards the
        # optical split where BPM/KEY formed one row and the values another.
        convert_controls = (
            window.quick_convert_bpm_label,
            window.quick_convert_bpm_switch,
            window.quick_convert_bpm,
            window.quick_convert_key_label,
            window.quick_convert_key_switch,
            window.quick_convert_key,
        )
        centers = {widget.geometry().center().y() for widget in convert_controls}
        self.assertEqual(len(centers), 1)
        self.assertEqual(window.quick_convert_settings.height(), 36)
        self.assertEqual(window.quick_convert_button.height(), 36)
        self.assertEqual(window.quick_convert_result.height(), 36)
        for field in (window.quick_convert_bpm, window.quick_convert_key):
            top = field.geometry().top() - window.quick_convert_settings.contentsRect().top()
            bottom = window.quick_convert_settings.contentsRect().bottom() - field.geometry().bottom()
            self.assertEqual(top, bottom)

        convert_contents = window.quick_convert_settings.contentsRect()
        self.assertLessEqual(
            window.quick_convert_settings.layout().minimumSize().width(),
            convert_contents.width(),
        )
        self.assertTrue(convert_contents.contains(window.quick_convert_key.geometry()))
        self.assertGreaterEqual(
            convert_contents.right() - window.quick_convert_key.geometry().right(),
            3,
        )

        for selector in (window.quick_extract_key, window.quick_convert_key):
            self.assertEqual(
                [selector.itemText(index) for index in range(selector.count())],
                list(window.quick_extract_key._items),
            )
            selector._show_menu()
            APP.processEvents()
            checked = [row for row in selector._rows.values() if row.isChecked()]
            self.assertEqual(len(checked), 1)
            visible_width = abs(
                selector.mapToGlobal(QPoint(selector.width(), 0)).x()
                - selector.mapToGlobal(QPoint(0, 0)).x()
            )
            self.assertGreaterEqual(selector._popup.width(), visible_width)
            selector._popup.hide()
        window.select_tab(0)
        APP.processEvents()
        selector = window.target_key_combo
        self.assertEqual([selector.itemText(index) for index in range(selector.count())], list(window.quick_extract_key._items))
        selector._show_menu()
        APP.processEvents()
        self.assertEqual(sum(row.isChecked() for row in selector._rows.values()), 1)
        selector._popup.hide()
        window.close()

    def test_scale_popup_fits_its_rows_and_current_screen_at_every_scale(self):
        window = MainWindow()
        window.show()
        APP.processEvents()

        selector = window.scale_select
        # The popup must be a native top-level surface.  If it is parented to
        # the selector, QGraphicsProxyWidget scales it a second time and the
        # lower choices disappear progressively above 100%.
        self.assertIsNone(selector._popup.parentWidget())
        self.assertTrue(selector._popup.isWindow())
        for percent in (100, 110, 120, 130, 140, 150):
            selector.setCurrentText(f"{percent}%")
            APP.processEvents()
            selector._show_menu()
            APP.processEvents()

            popup = selector._popup
            screen = popup.screen() or window.screen()
            self.assertIsNotNone(screen)
            self.assertTrue(screen.availableGeometry().contains(popup.frameGeometry()))
            self.assertGreaterEqual(popup.height(), popup.sizeHint().height())

            selector_rect = self.global_rect(selector)
            self.assertFalse(popup.frameGeometry().intersects(selector_rect))
            for row in selector._rows.values():
                self.assertGreaterEqual(row.width(), row.minimumSizeHint().width())
                self.assertGreaterEqual(
                    row.text_label.width(),
                    row.text_label.sizeHint().width(),
                )
            popup.hide()

        selector.setCurrentText("100%")
        window.close()

    def test_validated_column_boundaries_match_approved_crops(self):
        window = MainWindow()
        window.show()
        APP.processEvents()

        # The Source Folder row is intentionally split into two equal halves.
        self.assertLessEqual(
            abs(window.input_drop.width() - window.source_path_box.width()),
            2,
        )
        self.assertGreaterEqual(
            window.source_path_box.mapTo(window.canvas, QPoint(0, 0)).x(),
            505,
        )
        self.assertLessEqual(
            window.source_path_box.mapTo(window.canvas, QPoint(0, 0)).x(),
            520,
        )

        window.select_tab(1)
        APP.processEvents()
        extract_boundary = window.quick_layers_area.mapTo(window.canvas, QPoint(0, 0)).x()
        convert_boundary = window.quick_convert_drag.parentWidget().mapTo(window.canvas, QPoint(0, 0)).x()
        self.assertGreaterEqual(extract_boundary, 344)
        self.assertLessEqual(extract_boundary, 360)
        # Quick Convert now has a dedicated action column between its compact
        # target controls and result card.  The card must retain the remainder
        # of the approved fixed canvas without being cropped at the right edge.
        self.assertGreaterEqual(convert_boundary, 686)
        self.assertLessEqual(convert_boundary, 700)
        self.assertGreater(window.quick_layers_area.width(), 2 * window.quick_extract_drop.width() - 5)
        self.assertGreater(window.quick_convert_drag.parentWidget().width(), window.quick_convert_drop.width())

        convert_widgets = (
            window.quick_convert_drop,
            window.quick_convert_settings,
            window.quick_convert_button,
            window.quick_convert_drag.parentWidget(),
        )
        convert_parent = window.quick_convert_drop.parentWidget()
        for widget in convert_widgets:
            self.assertTrue(
                convert_parent.contentsRect().contains(widget.geometry()),
                f"{widget.objectName() or type(widget).__name__} is cropped by Quick Convert",
            )
        for left, right in zip(convert_widgets, convert_widgets[1:]):
            self.assertLess(left.geometry().right(), right.geometry().left())

        # UI scaling transforms the complete fixed canvas and must never alter
        # the approved internal column boundaries.
        for percent in (110, 120, 130, 140, 150):
            window.scale_select.setCurrentText(f"{percent}%")
            APP.processEvents()
            self.assertEqual(
                window.quick_layers_area.mapTo(window.canvas, QPoint(0, 0)).x(),
                extract_boundary,
            )
            self.assertEqual(
                window.quick_convert_drag.parentWidget().mapTo(window.canvas, QPoint(0, 0)).x(),
                convert_boundary,
            )
        window.close()

    def test_validated_drop_zones_accept_copy_through_graphics_view(self):
        window = MainWindow()
        window.show()
        APP.processEvents()

        self.assertTrue(window.acceptDrops())
        self.assertTrue(window.view.acceptDrops())
        self.assertTrue(window.view.viewport().acceptDrops())
        self.assertTrue(window.canvas.acceptDrops())
        self.assertTrue(window.proxy.acceptDrops())

        with tempfile.TemporaryDirectory(prefix="Stem Slicer é ") as root:
            audio = os.path.join(root, "Loop é test.mp3")
            open(audio, "wb").close()
            cases = (
                (0, window.input_drop, root),
                (1, window.quick_extract_drop, audio),
                (1, window.quick_scan_drop, audio),
                (1, window.quick_convert_drop, audio),
            )
            for tab, drop, path in cases:
                window.select_tab(tab)
                APP.processEvents()
                drop.pathChanged.disconnect()
                emitted = []
                drop.pathChanged.connect(emitted.append)
                mime = QMimeData()
                mime.setUrls([QUrl.fromLocalFile(path)])
                canvas_point = drop.mapTo(window.canvas, drop.rect().center())
                scene_point = window.proxy.mapToScene(QPointF(canvas_point))
                viewport_point = window.view.mapFromScene(scene_point)
                actions = Qt.CopyAction | Qt.MoveAction

                enter = QDragEnterEvent(viewport_point, actions, mime, Qt.LeftButton, Qt.NoModifier)
                QApplication.sendEvent(window.view.viewport(), enter)
                self.assertTrue(enter.isAccepted())
                self.assertEqual(enter.dropAction(), Qt.CopyAction)

                move = QDragMoveEvent(viewport_point, actions, mime, Qt.LeftButton, Qt.NoModifier)
                QApplication.sendEvent(window.view.viewport(), move)
                self.assertTrue(move.isAccepted())
                self.assertEqual(move.dropAction(), Qt.CopyAction)

                dropped = QDropEvent(QPointF(viewport_point), actions, mime, Qt.LeftButton, Qt.NoModifier)
                QApplication.sendEvent(window.view.viewport(), dropped)
                self.assertTrue(dropped.isAccepted())
                self.assertEqual(dropped.dropAction(), Qt.CopyAction)
                self.assertEqual(
                    os.path.normcase(os.path.normpath(drop.path)),
                    os.path.normcase(os.path.normpath(path)),
                )
                self.assertEqual(emitted, [drop.path])
                self.assertFalse(drop.highlighted)
        window.close()

    def test_windows_browse_dialog_uses_stable_top_level_owner(self):
        window = MainWindow()
        window.show()
        APP.processEvents()

        with patch.object(validated_ui.os, "name", "nt"), patch.object(
            validated_ui.QFileDialog,
            "getOpenFileName",
            return_value=("", ""),
        ) as audio_picker:
            window.quick_extract_drop.choose()
        self.assertIs(audio_picker.call_args.args[0], window)
        self.assertTrue(
            audio_picker.call_args.kwargs["options"] & QFileDialog.DontUseNativeDialog
        )

        with patch.object(validated_ui.os, "name", "nt"), patch.object(
            validated_ui.QFileDialog,
            "getExistingDirectory",
            return_value="",
        ) as folder_picker:
            window.input_drop.choose()
        self.assertIs(folder_picker.call_args.args[0], window)
        self.assertTrue(
            folder_picker.call_args.args[3] & QFileDialog.DontUseNativeDialog
        )
        self.assertTrue(window.canvas.isVisible())
        window.close()

    def test_target_key_popups_stay_inside_the_available_screen(self):
        window = MainWindow()
        window.show()
        APP.processEvents()
        window.convert_switch.setChecked(True)

        for percent in (100, 110, 120, 130, 140, 150):
            window.scale_select.setCurrentText(f"{percent}%")
            APP.processEvents()

            window.select_tab(1)
            APP.processEvents()
            for selector in (window.quick_extract_key, window.quick_convert_key):
                selector._show_menu()
                APP.processEvents()
                popup = selector._popup
                screen = popup.screen() or window.screen()
                self.assertTrue(screen.availableGeometry().contains(popup.frameGeometry()))
                self.assertGreaterEqual(popup.height(), popup.sizeHint().height())
                selector._popup.hide()

            window.select_tab(0)
            APP.processEvents()
            window.target_key_combo._show_menu()
            APP.processEvents()
            popup = window.target_key_combo._popup
            screen = popup.screen() or window.screen()
            self.assertTrue(screen.availableGeometry().contains(popup.frameGeometry()))
            self.assertGreaterEqual(popup.height(), popup.sizeHint().height())
            popup.hide()
        window.close()

    def test_quick_status_rows_follow_their_content_columns(self):
        window = MainWindow()
        window.show()
        window.select_tab(1)
        APP.processEvents()

        self.assertEqual(
            self.global_rect(window.quick_extract_result_footer).left(),
            self.global_rect(window.quick_layers_area).left(),
        )
        self.assertEqual(
            self.global_rect(window.quick_convert_status_footer).left(),
            self.global_rect(window.quick_convert_settings).left(),
        )
        self.assertEqual(window.quick_convert_filename.text(), "")
        self.assertEqual(window.quick_convert_footer_filename.text(), "Ready for one loop.")
        self.assertEqual(
            sum(
                child.isVisible() and child.text() == "Ready for one loop."
                for child in window.canvas.findChildren(QLabel)
            ),
            1,
        )
        window.close()

    def test_quick_scan_control_labels_keep_their_full_width(self):
        window = MainWindow()
        window.show()
        window.select_tab(1)
        APP.processEvents()

        for label_widget in (window.quick_degree_label, window.quick_notation_label):
            self.assertGreaterEqual(label_widget.width(), label_widget.minimumSizeHint().width())
        self.assertLess(
            self.global_rect(window.quick_degree_label).right(),
            self.global_rect(window.quick_major_button).left(),
        )
        self.assertLess(
            self.global_rect(window.quick_notation_label).right(),
            self.global_rect(window.quick_sharps_button).left(),
        )
        window.close()

    def test_quick_scan_drop_content_is_compact_and_centered(self):
        window = MainWindow()
        window.show()
        window.select_tab(1)
        APP.processEvents()
        drop = window.quick_scan_drop

        centers = (
            drop.icon.geometry().center().y(),
            drop.copy_host.geometry().center().y(),
            drop.browse.geometry().center().y(),
        )
        self.assertLessEqual(max(centers) - min(centers), 2)
        self.assertLess(drop.icon.geometry().right(), drop.copy_host.geometry().left())
        self.assertLess(drop.copy_host.geometry().right(), drop.browse.geometry().left())
        self.assertLess(drop.title_label.geometry().bottom(), drop.subtitle_label.geometry().top())
        self.assertLessEqual(drop.title_label.height(), QFontMetrics(drop.title_label.font()).height() + 2)
        self.assertLessEqual(drop.subtitle_label.height(), QFontMetrics(drop.subtitle_label.font()).height() + 2)
        for child in (drop.icon, drop.copy_host, drop.browse):
            self.assertTrue(drop.contentsRect().contains(child.geometry()))
        window.close()

    def test_operation_cards_only_expand_themselves(self):
        window = MainWindow()
        window.show()
        APP.processEvents()
        heights = {}
        for key_enabled, convert_enabled in ((False, False), (True, False), (False, True), (True, True)):
            window.key_switch.setChecked(key_enabled)
            window.convert_switch.setChecked(convert_enabled)
            APP.processEvents()
            values = (
                window.layer_operation_card.height(),
                window.key_operation_card.height(),
                window.target_operation_card.height(),
            )
            heights[(key_enabled, convert_enabled)] = values

        self.assertEqual({values[0] for values in heights.values()}, {47})
        self.assertEqual(heights[(False, False)], (47, 47, 47))
        self.assertEqual(heights[(True, False)], (47, 139, 47))
        self.assertEqual(heights[(False, True)], (47, 47, 110))
        self.assertEqual(heights[(True, True)], (47, 139, 110))
        self.assertLess(window.target_operation_card.geometry().bottom(), window.status_panel.geometry().top())
        window.close()

    def test_output_path_elides_middle_while_actions_stay_anchored(self):
        window = MainWindow()
        window.show()
        APP.processEvents()
        initial_buttons = (window.change_root_button.geometry(), window.open_folder_button.geometry())
        long_path = "/Users/nrgy/" + ("Very Long Loop Pack Folder/" * 18) + "Final Layers"
        window.custom_destination = long_path
        window._update_destination_preview()
        APP.processEvents()

        self.assertEqual(initial_buttons, (window.change_root_button.geometry(), window.open_folder_button.geometry()))
        self.assertIn("…", window.destination_path_label.text())
        self.assertTrue(window.destination_path_label.text().startswith("/Users"))
        self.assertTrue(window.destination_path_label.text().endswith("Loop Pack Name"))
        self.assertEqual(window.destination_path_label.toolTip(), os.path.join(long_path, "Loop Pack Name"))
        self.assertLess(window.destination_path_label.geometry().right(), window.change_root_button.geometry().left())
        window.close()

    def test_key_destination_has_one_selected_visual_state(self):
        window = MainWindow()
        self.assertTrue(window.copy_destination_button.property("active"))
        self.assertFalse(window.rename_destination_button.property("active"))
        window._set_destination_mode("rename_in_place")
        self.assertFalse(window.copy_destination_button.property("active"))
        self.assertTrue(window.rename_destination_button.property("active"))
        window.close()

    def test_quick_scan_locks_drop_while_engine_loads(self):
        with tempfile.TemporaryDirectory() as root:
            audio = os.path.join(root, "loop.wav")
            open(audio, "wb").close()
            window = MainWindow()
            window._start_key_engine = lambda: setattr(window, "key_engine_state", "loading")

            window._quick_scan_requested(audio)

            self.assertTrue(window.quick_scan_busy)
            self.assertFalse(window.quick_scan_drop.isEnabled())
            self.assertEqual(window.pending_quick_scan, audio)
            self.assertEqual(window.quick_scan_filename_label.text(), "loop.wav")
            self.assertIn("Loading", window.quick_scan_time_label.text())
            window._quick_scan_finished()
            window.close()

    def test_quick_scan_formats_result_without_rescanning(self):
        window = MainWindow()
        window.quick_scan_result = {"camelot": "3A", "bpm": 75.0}
        window._update_quick_scan_results()
        self.assertEqual(window.quick_bpm_value.text(), "150")
        self.assertEqual(window.quick_detected_value.text(), "A# minor")
        self.assertEqual(window.quick_relative_value.text(), "C# major")
        self.assertEqual(window.quick_detected_degree.text(), "VI")
        self.assertEqual(window.quick_relative_degree.text(), "I")
        self.assertEqual(window.quick_detected_modal.text(), "A# Aeolian · VI")
        self.assertEqual(window.quick_relative_modal.text(), "C# Ionian · I")

        window._set_quick_accidentals("flats")
        window._set_quick_degree_reference("minor")
        self.assertEqual(window.quick_detected_value.text(), "Bb minor")
        self.assertEqual(window.quick_relative_value.text(), "Db major")
        self.assertEqual(window.quick_detected_degree.text(), "I")
        self.assertEqual(window.quick_relative_degree.text(), "III")
        self.assertEqual(window.quick_bpm_value.text(), "150")
        window.close()

    def test_quick_scan_modes_stay_empty_until_a_real_result(self):
        window = MainWindow()
        self.assertTrue(all((key.text(), degree.text()) == ("—", "—") for key, degree in window.quick_mode_labels))
        self.assertIn("Scan a file", window.quick_modes_note.text())

        window._set_quick_accidentals("flats")
        window._set_quick_degree_reference("minor")
        self.assertTrue(all((key.text(), degree.text()) == ("—", "—") for key, degree in window.quick_mode_labels))

        window._set_quick_accidentals("sharps")
        window._set_quick_degree_reference("major")
        window.quick_scan_result = {"camelot": "3A"}
        window._update_quick_scan_results()
        self.assertEqual(
            [(key.text(), degree.text()) for key, degree in window.quick_mode_labels],
            [
                ("D# Dorian", "II"),
                ("F Phrygian", "III"),
                ("F# Lydian", "IV"),
                ("G# Mixolydian", "V"),
                ("C Locrian", "VII"),
            ],
        )
        self.assertEqual(window.quick_modes_note.text(), "Same notes · different centers")

        window._quick_scan_failed("test")
        self.assertTrue(all((key.text(), degree.text()) == ("—", "—") for key, degree in window.quick_mode_labels))
        self.assertEqual(window.quick_detected_value.text(), "—")
        self.assertEqual(window.quick_relative_value.text(), "—")
        window.close()

    def test_quick_scan_accepts_only_supported_audio_files(self):
        with tempfile.TemporaryDirectory() as root:
            drop = DropZone("audio", interactive=True)
            for extension in (".mp3", ".wav", ".flac"):
                path = os.path.join(root, "loop" + extension)
                open(path, "wb").close()
                self.assertTrue(drop.set_path(path))
            unsupported = os.path.join(root, "loop.aiff")
            open(unsupported, "wb").close()
            self.assertFalse(drop.set_path(unsupported))
            texts = [item.text() for item in drop.findChildren(QLabel)]
            self.assertIn("Supported formats: MP3, WAV, FLAC", texts)
            drop.close()

    def test_quick_extract_drop_accepts_only_mp3(self):
        with tempfile.TemporaryDirectory() as root:
            drop = DropZone("audio", interactive=True, allowed_extensions={".mp3"})
            mp3 = os.path.join(root, "loop.mp3"); wav = os.path.join(root, "loop.wav")
            open(mp3, "wb").close(); open(wav, "wb").close()
            self.assertTrue(drop.set_path(mp3))
            self.assertFalse(drop.set_path(wav))
            drop.close()

    def test_quick_extract_empty_state_is_centered_and_replaced_immediately(self):
        window = MainWindow()
        window.select_tab(1)
        window.show()
        APP.processEvents()

        self.assertEqual(
            window.quick_layers_empty_label.text(),
            "Once you drop an audio file, its layers will appear here.",
        )
        self.assertEqual(window.quick_layers_empty_icon.kind, "layers")
        empty_center = window.quick_layers_empty_state.mapTo(
            window.quick_layer_content,
            window.quick_layers_empty_state.rect().center(),
        ).y()
        self.assertLessEqual(abs(empty_center - window.quick_layer_content.rect().center().y()), 1)
        self.assertLess(
            window.quick_layers_empty_icon.geometry().bottom(),
            window.quick_layers_empty_label.geometry().top(),
        )

        initial_state = window.quick_layers_empty_state
        window._populate_layer_cards([], "Extracting layers…")
        self.assertFalse(initial_state.isVisible())
        self.assertEqual(window.quick_layers_empty_label.text(), "Extracting layers…")
        self.assertIsNone(window.quick_layers_empty_icon)

        processing_state = window.quick_layers_empty_state
        layer = {
            "path": "/private/tmp/quick-layer.mp3",
            "name": "quick-layer.mp3",
            "bpm": 140,
            "duration": 1.0,
            "bytes": 32,
            "peaks": [0.0] * 72,
        }
        window._populate_layer_cards([layer])
        self.assertFalse(processing_state.isVisible())
        self.assertIsNone(window.quick_layers_empty_state)
        QTest.qWait(20)
        self.assertEqual(len(window.layer_cards), 1)
        window.close()

    def test_quick_extract_status_keeps_audio_elapsed_time_during_midi(self):
        window = MainWindow()
        layer = {
            "path": "/private/tmp/quick-layer.mp3",
            "name": "quick-layer.mp3",
            "bpm": 140,
            "duration": 1.0,
            "bytes": 32,
            "peaks": [0.0] * 72,
        }
        with patch.object(window, "_queue_midi_conversion"):
            window._quick_extract_completed([layer], 2.34)
        self.assertIn("extracted in 2.3s", window.quick_extract_status.text())

        window.midi_job_id = 7
        window._midi_completed(7, 1, 0.5)
        self.assertIn("extracted in 2.3s", window.quick_extract_status.text())
        self.assertIn("1 MIDI file ready", window.quick_extract_status.text())
        window.close()

    def test_midi_starts_while_layer_cards_render_incrementally(self):
        window = MainWindow()
        layers = [
            {
                "path": f"/private/tmp/parallel-layer-{index}.mp3",
                "name": f"parallel-layer-{index}.mp3",
                "bpm": 140,
                "duration": 1.0,
                "bytes": 32,
                "peaks": [0.0] * 72,
            }
            for index in range(7)
        ]
        window.midi_engine_state = "ready"
        window.midi_worker = type("Worker", (), {"latest_job_id": 0})()
        requests = []
        window.midiRequested.connect(lambda *args: requests.append(args))
        window._populate_layer_cards(layers)
        self.assertEqual(window.layer_cards, [])
        window._queue_midi_conversion(layers)
        self.assertEqual(len(requests), 1)
        self.assertTrue(window._layer_cards_rendering)
        deadline = time.monotonic() + 2.0
        while len(window.layer_cards) < len(layers) and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertEqual(len(window.layer_cards), len(layers))
        window.close()

    def test_midi_result_waits_for_its_incremental_card(self):
        window = MainWindow()
        layer = {
            "path": "/private/tmp/early-midi-layer.mp3",
            "name": "early-midi-layer.mp3",
            "bpm": 140,
            "duration": 1.0,
            "bytes": 32,
            "peaks": [0.0] * 72,
        }
        window.midi_job_id = 4
        window._populate_layer_cards([layer])
        window._midi_progress(4, layer["path"], "/private/tmp/early.mid", 1, 1)
        self.assertEqual(window.pending_midi_paths[layer["path"]], "/private/tmp/early.mid")
        deadline = time.monotonic() + 2.0
        while not window.layer_cards and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertEqual(window.layer_cards[0].midi_handle.path, "/private/tmp/early.mid")
        self.assertNotIn(layer["path"], window.pending_midi_paths)
        window.close()

    def test_midi_completion_uses_job_total_before_all_cards_exist(self):
        window = MainWindow()
        window.midi_job_id = 5
        window.midi_job_total = 7
        window._midi_completed(5, 7, 0.1)
        self.assertIn("7 layers extracted", window.quick_extract_status.text())
        self.assertIn("7 MIDI files ready", window.quick_extract_status.text())
        window.close()

    def test_drag_all_tracks_every_layer_in_order(self):
        window = MainWindow()
        paths = [f"/private/tmp/layer-{index}.mp3" for index in range(1, 4)]
        window.quick_drag_all.set_paths(paths)
        self.assertTrue(window.quick_drag_all.isEnabled())
        self.assertEqual(window.quick_drag_all.paths, paths)
        self.assertIn("3 layers", window.quick_drag_all.toolTip())
        window.quick_drag_all.set_paths([])
        self.assertFalse(window.quick_drag_all.isEnabled())
        window.close()

    def test_quick_audio_drop_contents_never_overlap(self):
        """Protect the compact Quick Scan/Extract drop-zone composition."""
        previous_stylesheet = APP.styleSheet()
        APP.setStyleSheet(application_stylesheet())
        drops = []
        try:
            with tempfile.TemporaryDirectory() as root:
                loaded_audio = os.path.join(root, "L ENERGY 147 +NRGY.mp3")
                open(loaded_audio, "wb").close()

                # Reproduce the two states shown in the UI: an empty Quick Scan
                # drop and a Quick Extract drop displaying a selected filename.
                scan_drop = DropZone("audio", interactive=True)
                extract_drop = DropZone("audio", compact=True, interactive=True, allowed_extensions={".mp3"})
                self.assertTrue(extract_drop.set_path(loaded_audio))
                drops.extend((scan_drop, extract_drop))

                for drop in drops:
                    drop.show()
                APP.processEvents()

                for drop in drops:
                    ordered_widgets = (
                        drop.icon,
                        drop.title_label,
                        drop.subtitle_label,
                        drop.browse,
                        drop.formats_label,
                    )

                    for upper, lower in zip(ordered_widgets, ordered_widgets[1:]):
                        self.assertFalse(
                            upper.geometry().intersects(lower.geometry()),
                            f"{type(upper).__name__} overlaps {type(lower).__name__}",
                        )
                        self.assertLess(
                            upper.geometry().bottom(),
                            lower.geometry().top(),
                            f"{type(upper).__name__} must remain above {type(lower).__name__}",
                        )
                    self.assertLessEqual(
                        drop.formats_label.geometry().bottom(),
                        drop.contentsRect().bottom(),
                    )
        finally:
            for drop in drops:
                drop.close()
            APP.setStyleSheet(previous_stylesheet)
            APP.processEvents()

    def test_drop_zone_accepts_native_drag_move_and_drop(self):
        with tempfile.TemporaryDirectory() as root:
            audio = os.path.join(root, "loop.mp3")
            open(audio, "wb").close()
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(audio)])
            actions = Qt.CopyAction | Qt.MoveAction
            drop = DropZone("audio", interactive=True)

            enter = QDragEnterEvent(QPoint(10, 10), actions, mime, Qt.LeftButton, Qt.NoModifier)
            drop.dragEnterEvent(enter)
            self.assertTrue(enter.isAccepted())
            self.assertEqual(enter.dropAction(), Qt.CopyAction)

            move = QDragMoveEvent(QPoint(10, 10), actions, mime, Qt.LeftButton, Qt.NoModifier)
            drop.dragMoveEvent(move)
            self.assertTrue(move.isAccepted())
            self.assertEqual(move.dropAction(), Qt.CopyAction)

            dropped = QDropEvent(QPointF(10, 10), actions, mime, Qt.LeftButton, Qt.NoModifier)
            drop.dropEvent(dropped)
            self.assertTrue(dropped.isAccepted())
            self.assertEqual(dropped.dropAction(), Qt.CopyAction)
            self.assertEqual(drop.path, audio)
            drop.close()

    def test_folder_drop_accepts_native_drag_move_and_drop(self):
        with tempfile.TemporaryDirectory() as root:
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(root)])
            actions = Qt.CopyAction | Qt.MoveAction
            drop = DropZone("folder")

            move = QDragMoveEvent(QPoint(10, 10), actions, mime, Qt.LeftButton, Qt.NoModifier)
            drop.dragMoveEvent(move)
            self.assertTrue(move.isAccepted())
            self.assertEqual(move.dropAction(), Qt.CopyAction)

            dropped = QDropEvent(QPointF(10, 10), actions, mime, Qt.LeftButton, Qt.NoModifier)
            drop.dropEvent(dropped)
            self.assertTrue(dropped.isAccepted())
            self.assertEqual(drop.path, root)
            drop.close()

    def test_pause_mark_is_painted_instead_of_using_a_platform_glyph(self):
        layer = {"path": "/tmp/layer.mp3", "name": "layer.mp3", "duration": 1, "bytes": 1, "peaks": [0.5] * 72}
        card = LayerCard(layer)
        card.setPlaybackState("playing")
        self.assertEqual(card.play.text(), "")
        self.assertEqual(card.play.property("state"), "playing")
        card.setPlaybackState("paused")
        self.assertEqual(card.play.text(), "▶")
        card.close()

    def test_layer_card_midi_handle_becomes_draggable_when_ready(self):
        layer = {"path": "/tmp/layer.mp3", "name": "layer.mp3", "duration": 1, "bytes": 1, "peaks": [0.5] * 72}
        card = LayerCard(layer)
        self.assertEqual(card.midi_handle.state, "processing")
        self.assertEqual((card.midi_handle.width(), card.midi_handle.height()), (32, 20))
        card.setMidiPath("/tmp/layer_1.mid")
        self.assertEqual(card.midi_handle.state, "ready")
        self.assertEqual(card.midi_handle.path, "/tmp/layer_1.mid")
        card.close()

    def test_quick_extract_worker_returns_real_layer_metadata(self):
        with tempfile.TemporaryDirectory() as root:
            layer = os.path.join(root, "Loop_L1.mp3")
            with open(layer, "wb") as stream:
                stream.write(b"audio")
            diagnostics = [{
                "event": "exported", "output_exists": True,
                "output_name": "Loop_L1.mp3", "duration_seconds": 12.5,
                "output_bytes": 5,
            }]
            source = os.path.join(root, "Loop 140 C minor.mp3")
            open(source, "wb").close()
            worker = QuickExtractWorkflowWorker(
                None,
                source,
                root,
                bpm_enabled=False,
                bpm=None,
                key_enabled=False,
                key_pair=None,
            )
            results = []
            worker.completed.connect(lambda layers, elapsed: results.extend(layers))
            with patch("stem_workflow.process_single_file", return_value=diagnostics), patch("stem_workflow.waveform_peaks", return_value=[0.5] * 72):
                worker.run()
            APP.processEvents()
            self.assertEqual(results[0]["path"], layer)
            self.assertEqual(results[0]["duration"], 12.5)
            self.assertEqual(results[0]["bytes"], 5)
            self.assertEqual(len(results[0]["peaks"]), 72)

    def test_paused_layer_resumes_instead_of_stopping(self):
        class FakePlayer:
            def __init__(self): self.play_calls = 0
            def playbackState(self): return QMediaPlayer.PlaybackState.PausedState
            def play(self): self.play_calls += 1
            def stop(self): pass

        window = MainWindow(); fake = FakePlayer(); window.media_player = fake; window.active_layer_path = "/tmp/layer.mp3"
        window._toggle_layer_playback("/tmp/layer.mp3")
        self.assertEqual(fake.play_calls, 1)
        self.assertEqual(window.active_layer_path, "/tmp/layer.mp3")
        window.close()

    def test_waveform_scrubbing_reaches_both_extremes(self):
        waveform = WaveformWidget([0.5] * 72); waveform.resize(240, 22)
        values = []; waveform.seekRequested.connect(values.append)
        waveform._seek_from_x(240); waveform._seek_from_x(-10)
        self.assertEqual(values, [1.0, 0.0])
        waveform.setProgress(0.65)
        self.assertEqual(waveform.progress, 0.65)
        waveform.close()

    def test_each_edge_chip_can_cross_the_full_strip(self):
        strip = TokenStrip(TOKENS)
        strip.resize(700, 66)
        strip.setEnabled(True)
        strip.show()
        APP.processEvents()

        first = strip.chipRects()[0].center()
        last = strip.chipRects()[-1].center()
        QTest.mousePress(strip, Qt.LeftButton, Qt.NoModifier, QPoint(int(first.x()), int(first.y())))
        QTest.mouseMove(strip, QPoint(int(last.x() + 80), int(last.y())), 20)
        QTest.mouseRelease(strip, Qt.LeftButton, Qt.NoModifier, QPoint(int(last.x() + 80), int(last.y())))
        self.assertEqual(strip.tokens[-1], "KEY")

        last = strip.chipRects()[-1].center()
        first = strip.chipRects()[0].center()
        QTest.mousePress(strip, Qt.LeftButton, Qt.NoModifier, QPoint(int(last.x()), int(last.y())))
        QTest.mouseMove(strip, QPoint(max(2, int(first.x() - 80)), int(first.y())), 20)
        QTest.mouseRelease(strip, Qt.LeftButton, Qt.NoModifier, QPoint(max(2, int(first.x() - 80)), int(first.y())))
        self.assertEqual(strip.tokens[0], "KEY")
        strip.close()

    def test_stem_workflow_matrix(self):
        with tempfile.TemporaryDirectory() as source:
            open(os.path.join(source, "Loop 140 C minor.mp3"), "wb").close()
            window = MainWindow()
            window._start_key_engine = lambda: None
            window.key_engine_state = "ready"
            window.input_drop.set_path(source)

            # The validated 1.8B UI opens with extraction and key analysis on,
            # while conversion remains an explicit optional operation.
            self.assertTrue(window.layer_switch.isChecked())
            self.assertTrue(window.key_switch.isChecked())
            self.assertFalse(window.convert_switch.isChecked())
            self.assertEqual(window.start_button.text(), "▶  PROCESS 1 LOOP")
            self.assertTrue(window.start_button.isEnabled())
            self.assertFalse(window.copy_destination_button.isEnabled())
            self.assertTrue(window.key_panel.isVisibleTo(window.key_operation_card))
            self.assertFalse(window.target_panel.isVisibleTo(window.target_operation_card))

            window.layer_switch.setChecked(False)
            self.assertEqual(window.start_button.text(), "▶  PROCESS 1 LOOP")
            self.assertTrue(window.copy_destination_button.isEnabled())
            self.assertTrue(window.rename_destination_button.isEnabled())
            self.assertIn("Analyzed Loops", window.destination_path_label.toolTip())

            window.convert_switch.setChecked(True)
            self.assertEqual(window.start_button.text(), "▶  PROCESS 1 LOOP")
            self.assertFalse(window.copy_destination_button.isEnabled())
            self.assertTrue(window.target_panel.isVisibleTo(window.target_operation_card))
            self.assertIn("Converted Loops", window.destination_path_label.toolTip())

            window.key_switch.setChecked(False)
            self.assertEqual(window.start_button.text(), "▶  PROCESS 1 LOOP")
            self.assertTrue(window.start_button.isEnabled())

            window.convert_switch.setChecked(False)
            self.assertEqual(window.start_button.text(), "▶  PROCESS 1 LOOP")
            self.assertFalse(window.start_button.isEnabled())
            self.assertTrue(window.input_drop.isEnabled())
            window.close()

    def test_operation_cards_toggle_everywhere_without_switch_double_toggle(self):
        window = MainWindow()
        window.key_engine_state = "ready"
        window.show()
        APP.processEvents()

        key_header = window.key_switch.parentWidget()
        target_header = window.convert_switch.parentWidget()
        self.assertTrue(window.key_switch.isChecked())
        self.assertFalse(window.key_panel.isHidden())
        self.assertFalse(window.convert_switch.isChecked())
        self.assertTrue(window.target_panel.isHidden())

        # The whole operation header owns the same state as its switch.
        QTest.mouseClick(key_header, Qt.LeftButton, Qt.NoModifier, QPoint(key_header.width() - 35, key_header.height() // 2))
        self.assertFalse(window.key_switch.isChecked())
        self.assertTrue(window.key_panel.isHidden())

        QTest.mouseClick(target_header, Qt.LeftButton, Qt.NoModifier, QPoint(target_header.width() - 35, target_header.height() // 2))
        self.assertTrue(window.convert_switch.isChecked())
        self.assertFalse(window.target_panel.isHidden())

        # Key Analysis and Convert BPM & Key are independent and may remain
        # expanded together, matching the final validated prototype.
        QTest.mouseClick(key_header, Qt.LeftButton, Qt.NoModifier, QPoint(key_header.width() - 35, key_header.height() // 2))
        self.assertTrue(window.key_switch.isChecked())
        self.assertFalse(window.key_panel.isHidden())
        self.assertFalse(window.target_panel.isHidden())
        window.close()

    def test_output_action_buttons_are_vertically_centered(self):
        window = MainWindow()
        window.show()
        APP.processEvents()
        panel_center = window.layer_operation_card.rect().center().y()
        for action in (window.change_root_button, window.open_folder_button):
            action_center = action.mapTo(window.layer_operation_card, action.rect().center()).y()
            self.assertLessEqual(abs(action_center - panel_center), 1)
        self.assertEqual(window.change_root_button.height(), window.open_folder_button.height())
        self.assertGreaterEqual(
            window.open_folder_button.width(),
            QFontMetrics(window.open_folder_button.font()).horizontalAdvance(window.open_folder_button.text()) + 16,
        )
        window.close()

    def test_quick_tools_use_validated_extract_scan_convert_scopes(self):
        previous_stylesheet = APP.styleSheet()
        APP.setStyleSheet(application_stylesheet())
        window = MainWindow()
        window.key_engine_state = "ready"
        window.key_switch.setChecked(True)
        window.select_tab(1)
        window.show()
        APP.processEvents()
        try:
            self.assertEqual(window.quick_extract_drop.accent, RED)
            self.assertEqual(window.quick_scan_drop.accent, PURPLE)
            self.assertEqual(window.quick_convert_drop.accent, ORANGE)
            self.assertEqual(window.quick_extract_drop.browse.property("accent"), "red")
            self.assertEqual(window.quick_scan_drop.browse.property("accent"), "purple")
            self.assertEqual(window.quick_convert_drop.browse.property("accent"), "orange")

            page = window.pages.currentWidget()
            extract_y = window.quick_extract_drop.mapTo(page, QPoint()).y()
            scan_y = window.quick_scan_drop.mapTo(page, QPoint()).y()
            convert_y = window.quick_convert_drop.mapTo(page, QPoint()).y()
            self.assertLess(extract_y, scan_y)
            self.assertLess(scan_y, convert_y)
            self.assertNotEqual(window.quick_layers_area.verticalScrollBarPolicy(), Qt.ScrollBarAlwaysOff)
        finally:
            window.close()
            APP.setStyleSheet(previous_stylesheet)
            APP.processEvents()

    def test_guided_workflow_sections_are_ordered_and_fit(self):
        previous_stylesheet = APP.styleSheet()
        APP.setStyleSheet(application_stylesheet())
        window = MainWindow()
        window.show()
        APP.processEvents()
        try:
            texts = {item.text() for item in window.pages.widget(0).findChildren(QLabel)}
            self.assertIn("SOURCE FOLDER", texts)
            self.assertIn("OPERATIONS", texts)
            self.assertIn("LAYER EXTRACTION", texts)
            self.assertIn("KEY ANALYSIS", texts)
            self.assertIn("CONVERT BPM & KEY", texts)
            self.assertEqual(window.input_drop.title_label.text(), "Drop a loop folder here")
            self.assertFalse(window.layer_operation_card.isAncestorOf(window.input_drop))
            self.assertEqual(window.input_drop.icon.kind, "folder_in")
            self.assertEqual(window.open_folder_button.text(), "OPEN FOLDER")
            self.assertIn("KEY ANALYSIS DESTINATION", texts)
            self.assertEqual(window.stem_tab.icon.kind, "folder")

            page = window.pages.widget(0)
            previous_bottom = -1
            for section in window.workflow_sections:
                geometry = section.geometry()
                self.assertGreater(geometry.top(), previous_bottom)
                self.assertLessEqual(geometry.bottom(), page.contentsRect().bottom())
                previous_bottom = geometry.bottom()
        finally:
            window.close()
            APP.setStyleSheet(previous_stylesheet)
            APP.processEvents()

    def test_shared_source_stays_enabled_across_operations_and_busy(self):
        window = MainWindow()
        window.key_engine_state = "ready"

        for extract_enabled, key_enabled in ((True, False), (True, True), (False, True), (False, False)):
            window.layer_switch.setChecked(extract_enabled)
            window.key_switch.setChecked(key_enabled)
            self.assertTrue(window.input_drop.isEnabled())

        window.busy = True
        window._sync_stem_state()
        self.assertFalse(window.input_drop.isEnabled())
        self.assertFalse(window.layer_switch.isEnabled())
        self.assertFalse(window.key_switch.isEnabled())

        window.busy = False
        window._sync_stem_state()
        self.assertTrue(window.input_drop.isEnabled())
        window.close()

    def test_key_only_output_skin_and_destination_reset(self):
        window = MainWindow()
        window.key_engine_state = "ready"
        window.layer_switch.setChecked(False)
        window.key_switch.setChecked(True)

        self.assertEqual(window.start_button.property("role"), "process")
        self.assertTrue(window.copy_destination_button.isEnabled())
        self.assertTrue(window.rename_destination_button.isEnabled())
        window._set_destination_mode("rename_in_place")
        self.assertEqual(window.destination_mode, "rename_in_place")

        window.layer_switch.setChecked(True)
        self.assertEqual(window.destination_mode, "copy_to_output")
        self.assertFalse(window.copy_destination_button.isEnabled())
        self.assertFalse(window.rename_destination_button.isEnabled())
        self.assertIn("Extractions", window.destination_path_label.toolTip())
        window.close()

    def test_quick_tools_page_survives_stem_skin_state_changes(self):
        window = MainWindow()
        quick_page = window.pages.widget(1)
        quick_controls = (window.quick_scan_drop, window.quick_extract_drop, window.quick_layer_content)
        for control in quick_controls:
            self.assertTrue(quick_page.isAncestorOf(control))

        window.layer_switch.setChecked(False)
        window.key_switch.setChecked(True)
        QTest.mouseClick(window.quick_tab, Qt.LeftButton)
        APP.processEvents()
        self.assertIs(window.pages.currentWidget(), quick_page)
        for control in quick_controls:
            self.assertTrue(quick_page.isAncestorOf(control))
        window.close()

    def test_quick_target_switches_enable_only_their_own_fields(self):
        window = MainWindow()
        self.assertFalse(window.quick_extract_bpm.isEnabled())
        self.assertFalse(window.quick_extract_key.isEnabled())
        self.assertTrue(window.quick_convert_bpm.isEnabled())
        self.assertTrue(window.quick_convert_key.isEnabled())

        window.quick_extract_bpm_switch.setChecked(True)
        window.quick_convert_key_switch.setChecked(False)
        self.assertTrue(window.quick_extract_bpm.isEnabled())
        self.assertFalse(window.quick_extract_key.isEnabled())
        self.assertTrue(window.quick_convert_bpm.isEnabled())
        self.assertFalse(window.quick_convert_key.isEnabled())
        window.close()

    def test_quick_convert_drop_only_stages_the_source(self):
        with tempfile.TemporaryDirectory() as root:
            audio = os.path.join(root, "Loop 144 C minor.mp3")
            with open(audio, "wb") as stream:
                stream.write(b"audio")
            window = MainWindow()
            window.select_tab(1)
            with patch.object(window, "_run_quick_convert") as run_convert:
                self.assertTrue(window.quick_convert_drop.set_path(audio))
                APP.processEvents()

            run_convert.assert_not_called()
            self.assertFalse(window.quick_convert_busy)
            self.assertEqual(window.pending_quick_convert, "")
            self.assertEqual(window.quick_convert_path, audio)
            self.assertEqual(window.quick_convert_drop.path, audio)
            self.assertEqual(window.quick_convert_footer_filename.text(), os.path.basename(audio))
            self.assertIn("Loaded", window.quick_convert_footer_status.text())
            self.assertEqual(window.quick_convert_status.text(), "Ready to convert.")
            self.assertTrue(window.quick_convert_button.isEnabled())
            window.close()

    def test_quick_convert_button_tracks_source_targets_validation_and_busy_states(self):
        with tempfile.TemporaryDirectory() as root:
            audio = os.path.join(root, "Loop.mp3")
            open(audio, "wb").close()
            window = MainWindow()

            self.assertFalse(window.quick_convert_button.isEnabled())
            self.assertTrue(window.quick_convert_drop.set_path(audio))
            self.assertTrue(window.quick_convert_button.isEnabled())

            window.quick_convert_bpm_switch.setChecked(False)
            window.quick_convert_key_switch.setChecked(False)
            self.assertFalse(window.quick_convert_button.isEnabled())

            window.quick_convert_key_switch.setChecked(True)
            self.assertTrue(window.quick_convert_button.isEnabled())

            window.quick_convert_key_switch.setChecked(False)
            window.quick_convert_bpm_switch.setChecked(True)
            window.quick_convert_bpm.setText("0")
            self.assertFalse(window.quick_convert_button.isEnabled())
            window.quick_convert_bpm.setText("145")
            self.assertTrue(window.quick_convert_button.isEnabled())

            window.quick_scan_busy = True
            window._sync_quick_target_fields()
            self.assertFalse(window.quick_convert_button.isEnabled())
            window.quick_scan_busy = False
            window.busy = True
            window._sync_quick_target_fields()
            self.assertFalse(window.quick_convert_button.isEnabled())
            window.busy = False
            window._sync_quick_target_fields()
            self.assertTrue(window.quick_convert_button.isEnabled())
            window.close()

    def test_quick_convert_button_can_reuse_the_loaded_source(self):
        with tempfile.TemporaryDirectory() as root:
            audio = os.path.join(root, "Reusable Loop.mp3")
            open(audio, "wb").close()
            window = MainWindow()
            window.key_engine_state = "ready"
            window.select_tab(1)
            self.assertTrue(window.quick_convert_drop.set_path(audio))

            with patch.object(window, "_run_quick_convert") as run_convert:
                QTest.mouseClick(window.quick_convert_button, Qt.LeftButton)
                APP.processEvents()
                run_convert.assert_called_once_with(audio)
                self.assertTrue(window.quick_convert_busy)
                self.assertFalse(window.quick_convert_drop.isEnabled())
                self.assertFalse(window.quick_convert_button.isEnabled())

                window._quick_convert_finished()
                self.assertEqual(window.quick_convert_path, audio)
                self.assertEqual(window.quick_convert_drop.path, audio)
                self.assertTrue(window.quick_convert_button.isEnabled())

                window.quick_convert_bpm.setText("150")
                window.quick_convert_key.setCurrentText("D major / B minor")
                QTest.mouseClick(window.quick_convert_button, Qt.LeftButton)
                APP.processEvents()
                self.assertEqual(run_convert.call_count, 2)
                self.assertEqual(run_convert.call_args.args, (audio,))

            window._quick_convert_finished()
            self.assertEqual(window.quick_convert_path, audio)
            self.assertEqual(window.quick_convert_drop.path, audio)
            self.assertTrue(window.quick_convert_button.isEnabled())
            window.close()

    def test_quick_convert_button_recovers_after_batch_and_retries_engine_loading(self):
        with tempfile.TemporaryDirectory() as root:
            audio = os.path.join(root, "Retry Loop.mp3")
            open(audio, "wb").close()
            window = MainWindow()
            self.assertTrue(window.quick_convert_drop.set_path(audio))

            window.busy = True
            window._sync_quick_target_fields()
            self.assertFalse(window.quick_convert_button.isEnabled())
            with patch.object(validated_ui.FunctionalMainWindow, "_batch_finished") as finish:
                finish.side_effect = lambda: setattr(window, "busy", False)
                window._batch_finished()
            self.assertTrue(window.quick_convert_button.isEnabled())

            window.key_engine_state = "failed"
            with patch.object(window, "_start_key_engine") as start_engine:
                QTest.mouseClick(window.quick_convert_button, Qt.LeftButton)
                APP.processEvents()
            start_engine.assert_called_once_with()
            self.assertEqual(window.pending_quick_convert, audio)
            self.assertTrue(window.quick_convert_busy)
            window._quick_convert_finished()
            window.close()

    def test_pending_quick_operations_resume_when_key_engine_becomes_ready(self):
        window = MainWindow()
        class ReadyAnalyzer:
            def stop(self):
                pass

        analyzer = ReadyAnalyzer()
        window.pending_quick_scan = "/tmp/scan.mp3"
        window.pending_quick_extract = "/tmp/extract.mp3"
        window.pending_quick_convert = "/tmp/convert.mp3"
        with patch.object(window, "_run_quick_scan") as scan, \
             patch.object(window, "_run_quick_extract") as extract, \
             patch.object(window, "_run_quick_convert") as convert, \
             patch.object(window, "_start_midi_engine"):
            window._key_engine_ready(analyzer)
            APP.processEvents()

        scan.assert_called_once_with("/tmp/scan.mp3")
        extract.assert_called_once_with("/tmp/extract.mp3")
        convert.assert_called_once_with("/tmp/convert.mp3")
        self.assertIs(window.key_analyzer, analyzer)
        self.assertEqual(window.key_engine_state, "ready")
        window.close()

    def test_quick_extract_manager_lists_extracts_and_layers(self):
        with tempfile.TemporaryDirectory() as workspace:
            settings = MemorySettings(workspace); storage = StorageManager(settings)
            session = os.path.join(storage.category_path("quick"), "CUTDATROPE")
            os.makedirs(session)
            for index in range(1, 4):
                with open(os.path.join(session, f"CUTDATROPE_L{index}.mp3"), "wb") as stream:
                    stream.write(b"x" * index)
            dialog = QuickExtractManagerDialog(storage)
            self.assertIn("1 extract", dialog.summary.text())
            self.assertIn("3 layers", dialog.summary.text())
            self.assertTrue(any(item.text() == "CUTDATROPE" for item in dialog.findChildren(QLabel)))
            dialog.close()

    def test_key_analysis_controls_drive_settings_and_preview(self):
        window = MainWindow()
        window._start_key_engine = lambda: None
        window.key_engine_state = "ready"
        window.key_switch.setChecked(True)

        window._set_key_mode("relative_major")
        window._set_accidentals("flats")
        window._token_order_changed(["LOOP NAME", "BPM", "KEY", "PROD NAME"])

        settings = window._processing_settings()
        self.assertEqual(settings["mode"], "relative_major")
        self.assertEqual(settings["accidentals"], "flats")
        self.assertEqual(
            settings["token_order"],
            ["LOOP NAME", "BPM", "KEY", "PROD NAME"],
        )
        self.assertTrue(window.mode_buttons["relative_major"].property("active"))
        self.assertFalse(window.mode_buttons["detected"].property("active"))
        self.assertTrue(window.flats_button.property("active"))
        self.assertFalse(window.sharps_button.property("active"))
        self.assertIn("CALLMEUR3 137 Db +NRGY_L1.mp3", window.name_preview_label.text())
        window.close()

    def test_embedded_token_strip_updates_window_order(self):
        window = MainWindow()
        window._start_key_engine = lambda: None
        window.key_engine_state = "ready"
        window.key_switch.setChecked(True)
        window.show()
        APP.processEvents()

        strip = window.token_strip
        self.assertEqual(strip._font().pointSizeF(), 9.5)
        metrics = QFontMetrics(strip._font())
        for token, rect in zip(strip.tokens, strip.chipRects()):
            text_left = rect.center().x() - metrics.horizontalAdvance(token) / 2
            six_dot_grip_right = rect.left() + 18.5
            self.assertGreaterEqual(text_left - six_dot_grip_right, 2)
        widths = {token: rect.width() for token, rect in zip(strip.tokens, strip.chipRects())}
        self.assertGreater(widths["LOOP NAME"], widths["KEY"])
        self.assertGreater(widths["PROD NAME"], widths["BPM"])
        strip.tokens = ["LOOP NAME", "BPM", "PROD NAME", "KEY"]
        strip.orderChanged.emit(list(strip.tokens))
        APP.processEvents()
        self.assertEqual(window.token_order[-1], "KEY")
        self.assertIn("CALLMEUR3 137 +NRGY", window.name_preview_label.text())
        self.assertTrue(window.name_preview_label.text().endswith("A#m_L1.mp3"))
        window.close()

    def test_storage_preview_does_not_create_session(self):
        with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as source_parent:
            source = os.path.join(source_parent, "Untitled Folder")
            os.makedirs(source)
            window = MainWindow()
            window._start_key_engine = lambda: None
            window.key_engine_state = "ready"
            window.storage = StorageManager(MemorySettings(workspace))
            window.input_drop.set_path(source)

            expected = os.path.join(workspace, "Extractions", "Untitled Folder")
            self.assertEqual(window.destination_path_label.toolTip(), expected)
            self.assertFalse(os.path.exists(expected))

            window.key_switch.setChecked(True)
            window.layer_switch.setChecked(False)
            expected = os.path.join(workspace, "Analyzed Loops", "Untitled Folder")
            self.assertEqual(window.destination_path_label.toolTip(), expected)
            self.assertFalse(os.path.exists(expected))

            window._set_destination_mode("rename_in_place")
            self.assertEqual(window.destination_path_label.toolTip(), source)
            window.close()

    def test_selecting_source_refreshes_key_only_start_button(self):
        with tempfile.TemporaryDirectory() as source:
            open(os.path.join(source, "loop.mp3"), "wb").close()
            window = MainWindow()
            window._start_key_engine = lambda: None
            window.key_engine_state = "ready"

            window.key_switch.setChecked(True)
            window.layer_switch.setChecked(False)
            window.convert_switch.setChecked(False)
            self.assertFalse(window.start_button.isEnabled())

            # This is the exact cold-launch order reported by the user: the
            # engine is ready and Key Analysis is selected before the folder.
            window.input_drop.set_path(source)

            self.assertTrue(window.start_button.isEnabled())
            self.assertEqual(window.start_button.text(), "▶  PROCESS 1 LOOP")
            window.close()

    def test_custom_destination_is_session_only_and_direct(self):
        with tempfile.TemporaryDirectory() as custom, tempfile.TemporaryDirectory() as source_parent:
            source = os.path.join(source_parent, "Loop Pack")
            os.makedirs(source)
            window = MainWindow()
            window.show()
            window.input_drop.set_path(source)
            APP.processEvents()
            default_title_position = window.destination_path_label.mapTo(window.canvas, QPoint(0, 0))

            window.custom_destination = custom
            window._update_destination_preview()
            APP.processEvents()
            expected = os.path.join(custom, "Loop Pack")
            self.assertEqual(window.destination_path_label.toolTip(), expected)
            self.assertNotIn("Analyzed Loops", expected)
            self.assertNotIn("Extractions", expected)
            self.assertEqual(
                window.destination_path_label.mapTo(window.canvas, QPoint(0, 0)).y(),
                default_title_position.y(),
            )

            window._reset_destination()
            self.assertEqual(window.custom_destination, "")
            self.assertIn("Extractions", window.destination_path_label.toolTip())
            window.close()


if __name__ == "__main__":
    unittest.main()
