from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from tracker.services.labels import (
    AVERY_94051_HEIGHT,
    _draw_avery_94051_label,
    _draw_avery_94051_sheet,
    render_label_pdf,
)


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


class Avery94051DesignTests(SimpleTestCase):
    @patch("tracker.services.labels._draw_qr")
    def test_label_centers_qr_and_omits_scan_caption(self, draw_qr):
        pdf = MagicMock()
        batch = SimpleNamespace(
            name="My First Mead",
            start_date=date(2026, 7, 12),
            batch_number="001",
        )

        _draw_avery_94051_label(
            pdf,
            batch=batch,
            qr_url="https://mead.example.test/q/example/",
            x=10,
            y=20,
            include_batch_number=True,
            border_style="classic",
            border_color="forest",
            design_style="botanical",
        )

        qr_size = 0.64 * 72
        self.assertAlmostEqual(
            draw_qr.call_args.kwargs["y"],
            20 + (AVERY_94051_HEIGHT - qr_size) / 2,
        )
        drawn_text = [
            call.args[2]
            for call in pdf.drawString.call_args_list
            if len(call.args) >= 3
        ]
        self.assertNotIn("SCAN", drawn_text)

    def test_every_design_renders_a_valid_pdf(self):
        batch = SimpleNamespace(
            name="My First Mead",
            start_date=date(2026, 7, 12),
            batch_number="001",
        )

        for design_style in (
            "minimal",
            "modern",
            "botanical",
            "apothecary",
            "honeycomb",
            "premium",
        ):
            with self.subTest(design_style=design_style):
                result = render_label_pdf(
                    batch=batch,
                    qr_url="https://mead.example.test/q/example/",
                    width=Decimal("2.5"),
                    height=Decimal("1.5"),
                    dimension_unit="in",
                    copies=1,
                    output_mode="letter",
                    include_batch_number=True,
                    label_preset="avery-presta-94051",
                    border_style="classic",
                    border_color="amber",
                    design_style=design_style,
                )
                self.assertTrue(result.startswith(b"%PDF-"))
                self.assertGreater(len(result), 1_000)
