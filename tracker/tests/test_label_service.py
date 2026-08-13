from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from tracker.services.labels import _draw_avery_94051_sheet


class Avery94051SheetPlacementTests(SimpleTestCase):
    @patch("tracker.services.labels._draw_avery_94051_label")
    def test_start_position_skips_used_labels_in_row_major_order(self, draw_label):
        pdf = MagicMock()

        _draw_avery_94051_sheet(
            pdf,
            batch=MagicMock(),
            qr_url="https://mead.example.test/q/example/",
            copies=4,
            start_position=5,
            include_batch_number=True,
            border_style="classic",
            border_color="amber",
        )

        self.assertEqual(draw_label.call_count, 4)
        positions = [
            (call.kwargs["x"], call.kwargs["y"])
            for call in draw_label.call_args_list
        ]
        expected = [
            (216.0, 520.2),
            (405.36, 520.2),
            (26.64, 401.4),
            (216.0, 401.4),
        ]
        for position, expected_position in zip(positions, expected):
            self.assertAlmostEqual(position[0], expected_position[0])
            self.assertAlmostEqual(position[1], expected_position[1])
        pdf.showPage.assert_not_called()

    @patch("tracker.services.labels._draw_avery_94051_label")
    def test_start_position_continues_on_a_new_sheet(self, draw_label):
        pdf = MagicMock()

        _draw_avery_94051_sheet(
            pdf,
            batch=MagicMock(),
            qr_url="https://mead.example.test/q/example/",
            copies=4,
            start_position=17,
            include_batch_number=False,
            border_style="none",
            border_color="charcoal",
        )

        self.assertEqual(draw_label.call_count, 4)
        pdf.showPage.assert_called_once_with()
        positions = [
            (call.kwargs["x"], call.kwargs["y"])
            for call in draw_label.call_args_list
        ]
        expected = [
            (216.0, 45.0),
            (405.36, 45.0),
            (26.64, 639.0),
            (216.0, 639.0),
        ]
        for position, expected_position in zip(positions, expected):
            self.assertAlmostEqual(position[0], expected_position[0])
            self.assertAlmostEqual(position[1], expected_position[1])

    def test_start_position_must_be_on_the_first_sheet(self):
        with self.assertRaisesRegex(ValueError, "between 1 and 18"):
            _draw_avery_94051_sheet(
                MagicMock(),
                batch=MagicMock(),
                qr_url="https://mead.example.test/q/example/",
                copies=1,
                start_position=19,
                include_batch_number=True,
                border_style="classic",
                border_color="amber",
            )
