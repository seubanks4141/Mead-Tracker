from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO
from math import floor

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch, mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


INK = HexColor("#17261e")
MUTED = HexColor("#65756c")
ACCENT = HexColor("#bd7834")
PAPER = HexColor("#fffdf7")


@dataclass(frozen=True)
class LabelSpec:
    width: float
    height: float
    copies: int = 1
    output_mode: str = "single"
    include_batch_number: bool = True


def to_points(value: Decimal, unit: str) -> float:
    multiplier = inch if unit == "in" else mm
    return float(value) * multiplier


def _fit_text_size(
    text: str,
    available_width: float,
    preferred: float,
    minimum: float,
    font_name: str = "Helvetica-Bold",
) -> float:
    size = preferred
    while size > minimum and stringWidth(text, font_name, size) > available_width:
        size -= 0.5
    return max(size, minimum)


def _wrap_name(text: str, available_width: float, font_size: float) -> list[str]:
    words = text.split()
    if not words:
        return ["Untitled mead"]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if stringWidth(candidate, "Helvetica-Bold", font_size) <= available_width:
            current = candidate
        else:
            lines.append(current)
            current = word
            if len(lines) == 1:
                break
    if len(lines) < 2:
        lines.append(current)
    consumed = " ".join(lines)
    if consumed != text and len(lines) == 2:
        last = lines[-1]
        while last and stringWidth(
            f"{last}…", "Helvetica-Bold", font_size
        ) > available_width:
            last = last[:-1].rstrip()
        lines[-1] = f"{last}…"
    fitted_lines = []
    for line in lines[:2]:
        if stringWidth(line, "Helvetica-Bold", font_size) <= available_width:
            fitted_lines.append(line)
            continue
        shortened = line
        while shortened and stringWidth(
            f"{shortened}…", "Helvetica-Bold", font_size
        ) > available_width:
            shortened = shortened[:-1]
        fitted_lines.append(f"{shortened.rstrip()}…")
    return fitted_lines


def _draw_qr(
    pdf: canvas.Canvas,
    value: str,
    *,
    x: float,
    y: float,
    size: float,
) -> None:
    quiet = max(4.0, size * 0.045)
    pdf.setFillColor(white)
    pdf.roundRect(
        x - quiet,
        y - quiet,
        size + quiet * 2,
        size + quiet * 2,
        quiet,
        stroke=0,
        fill=1,
    )
    widget = QrCodeWidget(value, barLevel="Q")
    x1, y1, x2, y2 = widget.getBounds()
    drawing = Drawing(
        size,
        size,
        transform=[
            size / (x2 - x1),
            0,
            0,
            size / (y2 - y1),
            0,
            0,
        ],
    )
    drawing.add(widget)
    renderPDF.draw(drawing, pdf, x, y)


def _draw_one_label(
    pdf: canvas.Canvas,
    *,
    batch,
    qr_url: str,
    x: float,
    y: float,
    width: float,
    height: float,
    include_batch_number: bool,
    show_cut_line: bool,
) -> None:
    pdf.saveState()
    if show_cut_line:
        pdf.setStrokeColor(HexColor("#c9cec9"))
        pdf.setLineWidth(0.35)
        pdf.rect(x, y, width, height, stroke=1, fill=0)

    inset = max(10.0, min(width, height) * 0.055)
    pdf.setFillColor(PAPER)
    pdf.rect(
        x + (0.5 if show_cut_line else 0),
        y + (0.5 if show_cut_line else 0),
        width - (1 if show_cut_line else 0),
        height - (1 if show_cut_line else 0),
        stroke=0,
        fill=1,
    )

    available = width - inset * 2
    preferred_size = min(24.0, max(14.0, width / 12.5))
    name_size = _fit_text_size(batch.name, available, preferred_size, 11.0)
    lines = _wrap_name(batch.name, available, name_size)

    top = y + height - inset
    pdf.setFillColor(ACCENT)
    pdf.setFont("Helvetica-Bold", 7.5)
    pdf.drawString(x + inset, top - 2, "MEAD")

    pdf.setFillColor(INK)
    pdf.setFont("Helvetica-Bold", name_size)
    line_y = top - name_size - 9
    for line in lines:
        pdf.drawString(x + inset, line_y, line)
        line_y -= name_size * 1.08

    meta_y = line_y - 3
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 8.5)
    pdf.drawString(
        x + inset,
        meta_y,
        f"Started {_portable_started_date(batch)}",
    )

    if include_batch_number and batch.batch_number:
        pdf.drawString(x + inset, meta_y - 12, f"Batch {batch.batch_number}")

    qr_size = min(width * 0.46, height * 0.41, 1.30 * inch)
    qr_x = x + (width - qr_size) / 2
    qr_y = y + inset + 16
    _draw_qr(pdf, qr_url, x=qr_x, y=qr_y, size=qr_size)

    pdf.setFillColor(INK)
    pdf.setFont("Helvetica-Bold", 7.5)
    caption = "SCAN TO UPDATE"
    caption_width = stringWidth(caption, "Helvetica-Bold", 7.5)
    pdf.drawString(x + (width - caption_width) / 2, y + inset - 1, caption)
    pdf.restoreState()


def _portable_started_date(batch) -> str:
    """Return a date without platform-specific strftime modifiers."""

    return f"{batch.start_date.strftime('%b')} {batch.start_date.day}, {batch.start_date.year}"


def render_label_pdf(
    *,
    batch,
    qr_url: str,
    width: Decimal,
    height: Decimal,
    dimension_unit: str,
    copies: int,
    output_mode: str,
    include_batch_number: bool,
) -> bytes:
    """Render exact-size labels or a generic cut-it-yourself Letter sheet."""

    label_width = to_points(width, dimension_unit)
    label_height = to_points(height, dimension_unit)
    stream = BytesIO()

    if output_mode == "letter":
        page_width, page_height = letter
    else:
        page_width, page_height = label_width, label_height

    pdf = canvas.Canvas(stream, pagesize=(page_width, page_height))
    if output_mode == "letter":
        margin = 0.25 * inch
        gap = 0.125 * inch
        columns = max(1, floor((page_width - margin * 2 + gap) / (label_width + gap)))
        rows = max(1, floor((page_height - margin * 2 + gap) / (label_height + gap)))
        per_page = columns * rows
        grid_width = columns * label_width + (columns - 1) * gap
        grid_height = rows * label_height + (rows - 1) * gap
        origin_x = (page_width - grid_width) / 2
        origin_y = (page_height - grid_height) / 2

        for copy_index in range(copies):
            slot = copy_index % per_page
            if slot == 0 and copy_index:
                pdf.showPage()
            row = slot // columns
            column = slot % columns
            x = origin_x + column * (label_width + gap)
            y = origin_y + (rows - row - 1) * (label_height + gap)
            _draw_one_label(
                pdf,
                batch=batch,
                qr_url=qr_url,
                x=x,
                y=y,
                width=label_width,
                height=label_height,
                include_batch_number=include_batch_number,
                show_cut_line=True,
            )
    else:
        for copy_index in range(copies):
            if copy_index:
                pdf.showPage()
            _draw_one_label(
                pdf,
                batch=batch,
                qr_url=qr_url,
                x=0,
                y=0,
                width=label_width,
                height=label_height,
                include_batch_number=include_batch_number,
                show_cut_line=False,
            )
    pdf.save()

    return stream.getvalue()
