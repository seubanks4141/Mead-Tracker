from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO
from math import cos, floor, pi, sin

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

AVERY_PRESTA_94051 = "avery-presta-94051"
AVERY_94051_COLUMNS = 3
AVERY_94051_ROWS = 6
AVERY_94051_LABELS_PER_SHEET = AVERY_94051_COLUMNS * AVERY_94051_ROWS
AVERY_94051_WIDTH = 2.5 * inch
AVERY_94051_HEIGHT = 1.5 * inch
AVERY_94051_SIDE_MARGIN = 0.37 * inch
AVERY_94051_TOP_MARGIN = 0.625 * inch

BORDER_COLORS = {
    "amber": HexColor("#9b5a1a"),
    "forest": HexColor("#315e45"),
    "burgundy": HexColor("#7a3040"),
    "navy": HexColor("#334e68"),
    "charcoal": HexColor("#3f4642"),
}

DESIGN_MINIMAL = "minimal"
DESIGN_MODERN = "modern"
DESIGN_BOTANICAL = "botanical"
DESIGN_APOTHECARY = "apothecary"
DESIGN_HONEYCOMB = "honeycomb"
DESIGN_PREMIUM = "premium"
AVERY_94051_DESIGNS = {
    DESIGN_MINIMAL,
    DESIGN_MODERN,
    DESIGN_BOTANICAL,
    DESIGN_APOTHECARY,
    DESIGN_HONEYCOMB,
    DESIGN_PREMIUM,
}


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


def _wrap_name(
    text: str,
    available_width: float,
    font_size: float,
    font_name: str = "Helvetica-Bold",
) -> list[str]:
    words = text.split()
    if not words:
        return ["Untitled mead"]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if stringWidth(candidate, font_name, font_size) <= available_width:
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
            f"{last}...", font_name, font_size
        ) > available_width:
            last = last[:-1].rstrip()
        lines[-1] = f"{last}..."
    fitted_lines = []
    for line in lines[:2]:
        if stringWidth(line, font_name, font_size) <= available_width:
            fitted_lines.append(line)
            continue
        shortened = line
        while shortened and stringWidth(
            f"{shortened}...", font_name, font_size
        ) > available_width:
            shortened = shortened[:-1]
        fitted_lines.append(f"{shortened.rstrip()}...")
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


def _draw_decorative_border(
    pdf: canvas.Canvas,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    shape: str,
    border_style: str,
    border_color: str,
) -> None:
    if border_style == "none":
        return

    color = BORDER_COLORS.get(border_color, BORDER_COLORS["amber"])
    outer_inset = max(3.5, min(width, height) * 0.04)

    def draw_outline(inset: float) -> None:
        outline_x = x + inset
        outline_y = y + inset
        outline_width = width - inset * 2
        outline_height = height - inset * 2
        if shape == "oval":
            pdf.ellipse(
                outline_x,
                outline_y,
                outline_x + outline_width,
                outline_y + outline_height,
                stroke=1,
                fill=0,
            )
        else:
            radius = min(8.0, outline_width * 0.04, outline_height * 0.04)
            pdf.roundRect(
                outline_x,
                outline_y,
                outline_width,
                outline_height,
                radius,
                stroke=1,
                fill=0,
            )

    pdf.saveState()
    pdf.setStrokeColor(color)
    pdf.setLineWidth(1.0)
    if border_style == "dotted":
        pdf.setLineCap(1)
        pdf.setDash(0.5, 2.8)
    draw_outline(outer_inset)
    if border_style == "double":
        pdf.setLineWidth(0.65)
        draw_outline(outer_inset + max(3.0, min(width, height) * 0.035))
    pdf.restoreState()


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
    border_style: str,
    border_color: str,
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
    _draw_decorative_border(
        pdf,
        x=x,
        y=y,
        width=width,
        height=height,
        shape="rectangle",
        border_style=border_style,
        border_color=border_color,
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


def _normalize_avery_design(design_style: str) -> str:
    if design_style in AVERY_94051_DESIGNS:
        return design_style
    return DESIGN_HONEYCOMB


def _avery_theme(design_style: str, border_color: str) -> dict:
    design_style = _normalize_avery_design(design_style)
    accent = BORDER_COLORS.get(border_color, BORDER_COLORS["amber"])
    themes = {
        DESIGN_MINIMAL: {
            "background": HexColor("#fffaf0"),
            "text": HexColor("#2b211b"),
            "muted": HexColor("#73665d"),
            "font": "Times-Bold",
            "body_font": "Times-Roman",
        },
        DESIGN_MODERN: {
            "background": HexColor("#252827"),
            "text": white,
            "muted": HexColor("#ddd8cd"),
            "font": "Helvetica-Bold",
            "body_font": "Helvetica",
        },
        DESIGN_BOTANICAL: {
            "background": HexColor("#fbf7e9"),
            "text": HexColor("#23392d"),
            "muted": HexColor("#637067"),
            "font": "Times-Bold",
            "body_font": "Times-Roman",
        },
        DESIGN_APOTHECARY: {
            "background": HexColor("#f4ead4"),
            "text": HexColor("#3d2822"),
            "muted": HexColor("#746158"),
            "font": "Times-Bold",
            "body_font": "Times-Roman",
        },
        DESIGN_HONEYCOMB: {
            "background": HexColor("#fff8e8"),
            "text": HexColor("#29231e"),
            "muted": HexColor("#71675e"),
            "font": "Helvetica-Bold",
            "body_font": "Helvetica",
        },
        DESIGN_PREMIUM: {
            "background": HexColor("#14283b"),
            "text": white,
            "muted": HexColor("#d6dde0"),
            "font": "Times-Bold",
            "body_font": "Times-Roman",
        },
    }
    return {**themes[design_style], "design": design_style, "accent": accent}


def _draw_hexagon(
    pdf: canvas.Canvas,
    center_x: float,
    center_y: float,
    radius: float,
) -> None:
    points = [
        (
            center_x + radius * cos(pi / 3 * index),
            center_y + radius * sin(pi / 3 * index),
        )
        for index in range(6)
    ]
    path = pdf.beginPath()
    path.moveTo(*points[0])
    for point in points[1:]:
        path.lineTo(*point)
    path.close()
    pdf.drawPath(path, stroke=1, fill=0)


def _draw_leaf(
    pdf: canvas.Canvas,
    center_x: float,
    center_y: float,
    width: float,
    height: float,
    angle: float,
) -> None:
    pdf.saveState()
    pdf.translate(center_x, center_y)
    pdf.rotate(angle)
    pdf.ellipse(-width / 2, -height / 2, width / 2, height / 2, stroke=1, fill=0)
    pdf.restoreState()


def _draw_avery_theme_art(
    pdf: canvas.Canvas,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    theme: dict,
) -> None:
    """Paint a theme inside the oval while keeping the surrounding sheet clean."""

    design_style = theme["design"]
    accent = theme["accent"]
    pdf.saveState()
    oval = pdf.beginPath()
    oval.ellipse(x, y, width, height)
    pdf.clipPath(oval, stroke=0, fill=0)
    pdf.setFillColor(theme["background"])
    pdf.rect(x, y, width, height, stroke=0, fill=1)
    pdf.setStrokeColor(accent)
    pdf.setFillColor(accent)

    if design_style == DESIGN_MINIMAL:
        pdf.setLineWidth(0.55)
        pdf.line(x + width * 0.14, y + height * 0.78, x + width * 0.39, y + height * 0.78)
        pdf.line(x + width * 0.61, y + height * 0.22, x + width * 0.86, y + height * 0.22)
    elif design_style == DESIGN_MODERN:
        pdf.rect(x + width * 0.69, y, width * 0.31, height, stroke=0, fill=1)
        pdf.setLineWidth(2.2)
        pdf.line(x + width * 0.13, y + height * 0.75, x + width * 0.28, y + height * 0.75)
    elif design_style == DESIGN_BOTANICAL:
        pdf.setLineWidth(0.65)
        pdf.line(x + width * 0.02, y + height * 0.20, x + width * 0.11, y + height * 0.69)
        pdf.line(x + width * 0.90, y + height * 0.72, x + width * 0.98, y + height * 0.34)
        for leaf in (
            (0.035, 0.35, 9, 4, 48),
            (0.065, 0.47, 10, 4, -35),
            (0.085, 0.58, 9, 4, 48),
            (0.925, 0.61, 9, 4, 36),
            (0.95, 0.50, 10, 4, -48),
            (0.975, 0.40, 9, 4, 36),
        ):
            _draw_leaf(
                pdf,
                x + width * leaf[0],
                y + height * leaf[1],
                leaf[2],
                leaf[3],
                leaf[4],
            )
    elif design_style == DESIGN_APOTHECARY:
        pdf.setLineWidth(0.6)
        for line_y in (0.20, 0.80):
            pdf.line(x + width * 0.13, y + height * line_y, x + width * 0.38, y + height * line_y)
            pdf.line(x + width * 0.62, y + height * line_y, x + width * 0.87, y + height * line_y)
            center_y = y + height * line_y
            center_x = x + width * 0.5
            diamond = pdf.beginPath()
            diamond.moveTo(center_x, center_y + 3)
            diamond.lineTo(center_x + 4, center_y)
            diamond.lineTo(center_x, center_y - 3)
            diamond.lineTo(center_x - 4, center_y)
            diamond.close()
            pdf.drawPath(diamond, stroke=1, fill=0)
    elif design_style == DESIGN_HONEYCOMB:
        pdf.setLineWidth(0.55)
        for hex_x, hex_y, radius in (
            (0.02, 0.58, 9),
            (0.06, 0.72, 9),
            (0.015, 0.86, 9),
            (0.95, 0.25, 9),
            (0.99, 0.39, 9),
            (0.95, 0.53, 9),
        ):
            _draw_hexagon(
                pdf,
                x + width * hex_x,
                y + height * hex_y,
                radius,
            )
    elif design_style == DESIGN_PREMIUM:
        pdf.setLineWidth(0.6)
        pdf.line(x + width * 0.11, y + height * 0.82, x + width * 0.37, y + height * 0.82)
        pdf.line(x + width * 0.63, y + height * 0.18, x + width * 0.89, y + height * 0.18)
        pdf.circle(x + width * 0.11, y + height * 0.82, 2.2, stroke=1, fill=0)
        pdf.circle(x + width * 0.89, y + height * 0.18, 2.2, stroke=1, fill=0)

    pdf.restoreState()


def _draw_avery_94051_label(
    pdf: canvas.Canvas,
    *,
    batch,
    qr_url: str,
    x: float,
    y: float,
    include_batch_number: bool,
    border_style: str,
    border_color: str,
    design_style: str,
) -> None:
    """Draw one selectable, compact design inside a 94051 oval."""

    width = AVERY_94051_WIDTH
    height = AVERY_94051_HEIGHT
    theme = _avery_theme(design_style, border_color)
    pdf.saveState()
    _draw_avery_theme_art(
        pdf,
        x=x,
        y=y,
        width=width,
        height=height,
        theme=theme,
    )
    _draw_decorative_border(
        pdf,
        x=x,
        y=y,
        width=width,
        height=height,
        shape="oval",
        border_style=border_style,
        border_color=border_color,
    )

    text_x = x + 0.35 * inch
    text_width = 1.02 * inch
    name_size = 10.8 if theme["design"] == DESIGN_MODERN else 10.3
    name_font = theme["font"]
    name_lines = _wrap_name(batch.name, text_width, name_size, name_font)
    top = y + height - 0.38 * inch

    pdf.setFillColor(theme["accent"])
    pdf.setFont("Helvetica-Bold", 5.2)
    pdf.drawString(text_x, top, "HANDCRAFTED MEAD")

    pdf.setFillColor(theme["text"])
    pdf.setFont(name_font, name_size)
    name_y = top - 13.5
    for line in name_lines:
        pdf.drawString(text_x, name_y, line)
        name_y -= name_size * 1.03

    pdf.setFillColor(theme["muted"])
    pdf.setFont(theme["body_font"], 6.2)
    pdf.drawString(text_x, name_y - 1.5, f"Started {_portable_started_date(batch)}")
    if include_batch_number and batch.batch_number:
        pdf.setFont("Helvetica-Bold", 5.5)
        pdf.drawString(text_x, name_y - 10, f"Batch {batch.batch_number}")

    qr_size = 0.64 * inch
    qr_x = x + 1.57 * inch
    qr_y = y + (height - qr_size) / 2 + 4
    _draw_qr(pdf, qr_url, x=qr_x, y=qr_y, size=qr_size)

    pdf.setFillColor(theme["text"])
    pdf.setFont("Helvetica-Bold", 5.2)
    caption = "SCAN"
    caption_width = stringWidth(caption, "Helvetica-Bold", 5.2)
    pdf.drawString(qr_x + (qr_size - caption_width) / 2, y + 0.23 * inch, caption)
    pdf.restoreState()


def _draw_avery_94051_sheet(
    pdf: canvas.Canvas,
    *,
    batch,
    qr_url: str,
    copies: int,
    start_position: int,
    include_batch_number: bool,
    border_style: str,
    border_color: str,
    design_style: str = DESIGN_HONEYCOMB,
) -> None:
    if not 1 <= start_position <= AVERY_94051_LABELS_PER_SHEET:
        raise ValueError("Avery 94051 start position must be between 1 and 18.")

    page_width, page_height = letter
    horizontal_gap = (
        page_width
        - AVERY_94051_SIDE_MARGIN * 2
        - AVERY_94051_COLUMNS * AVERY_94051_WIDTH
    ) / (AVERY_94051_COLUMNS - 1)
    vertical_gap = (
        page_height
        - AVERY_94051_TOP_MARGIN * 2
        - AVERY_94051_ROWS * AVERY_94051_HEIGHT
    ) / (AVERY_94051_ROWS - 1)

    first_slot = start_position - 1
    for copy_index in range(copies):
        absolute_slot = first_slot + copy_index
        slot = absolute_slot % AVERY_94051_LABELS_PER_SHEET
        if slot == 0 and copy_index:
            pdf.showPage()
        row = slot // AVERY_94051_COLUMNS
        column = slot % AVERY_94051_COLUMNS
        x = AVERY_94051_SIDE_MARGIN + column * (
            AVERY_94051_WIDTH + horizontal_gap
        )
        y = (
            page_height
            - AVERY_94051_TOP_MARGIN
            - AVERY_94051_HEIGHT
            - row * (AVERY_94051_HEIGHT + vertical_gap)
        )
        _draw_avery_94051_label(
            pdf,
            batch=batch,
            qr_url=qr_url,
            x=x,
            y=y,
            include_batch_number=include_batch_number,
            border_style=border_style,
            border_color=border_color,
            design_style=design_style,
        )


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
    label_preset: str = "",
    border_style: str = "classic",
    border_color: str = "amber",
    design_style: str = DESIGN_HONEYCOMB,
    start_position: int = 1,
) -> bytes:
    """Render exact-size labels or a generic cut-it-yourself Letter sheet."""

    label_width = to_points(width, dimension_unit)
    label_height = to_points(height, dimension_unit)
    stream = BytesIO()

    if output_mode == "letter" or label_preset == AVERY_PRESTA_94051:
        page_width, page_height = letter
    else:
        page_width, page_height = label_width, label_height

    pdf = canvas.Canvas(stream, pagesize=(page_width, page_height))
    if label_preset == AVERY_PRESTA_94051:
        _draw_avery_94051_sheet(
            pdf,
            batch=batch,
            qr_url=qr_url,
            copies=copies,
            start_position=start_position,
            include_batch_number=include_batch_number,
            border_style=border_style,
            border_color=border_color,
            design_style=design_style,
        )
    elif output_mode == "letter":
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
                border_style=border_style,
                border_color=border_color,
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
                border_style=border_style,
                border_color=border_color,
            )
    pdf.save()

    return stream.getvalue()
