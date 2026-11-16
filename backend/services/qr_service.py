"""
backend/services/qr_service.py
Secure random QR ID generation and printable 54-tag A4 PDF generation.
"""
from __future__ import annotations

import io
import math
import secrets
from pathlib import Path
from typing import List

import qrcode
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from backend.config import BASE_URL, TAGS_PDF_DIR

# 32 unambiguous characters (excludes 0, O, 1, I, L)
SAFE_CHARSET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
ID_PREFIX = "TS-"
ID_CODE_LENGTH = 8


def generate_qr_id() -> str:
    """Generate a single cryptographically secure, non-sequential QR ID."""
    code = "".join(secrets.choice(SAFE_CHARSET) for _ in range(ID_CODE_LENGTH))
    return f"{ID_PREFIX}{code}"


def generate_unique_qr_ids(count: int, existing_ids: set[str] | None = None) -> list[str]:
    """Generate `count` distinct QR IDs that do not collide with existing database IDs."""
    existing = existing_ids or set()
    new_ids: list[str] = []
    while len(new_ids) < count:
        candidate = generate_qr_id()
        if candidate not in existing and candidate not in new_ids:
            new_ids.append(candidate)
    return new_ids


def make_qr_image(url: str) -> Image.Image:
    """
    Generate QR code image at error correction level Q (allows up to ~25% damage/wear).
    """
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_Q,
        box_size=6,
        border=1,
    )
    qr.add_data(url)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB")


def generate_tags_pdf(qr_ids: list[str], batch_no: str, base_url: str = BASE_URL) -> Path:
    """
    Generate an A4 PDF with exactly 54 tags per page (6 columns x 9 rows).
    Each tag includes:
      - High-contrast Error Correction Level Q QR Code pointing to permanent certificate URL.
      - Short human-readable QR ID printed beneath the QR code.
      - Subtle cut boundary guidelines.
    """
    pdf_filename = f"tags_{batch_no}.pdf"
    pdf_path = TAGS_PDF_DIR / pdf_filename

    # A4 Dimensions: 210mm x 297mm (approx 595.28 x 841.89 pt)
    page_width, page_height = A4
    cols = 6
    rows = 9
    tags_per_page = cols * rows  # 54

    left_margin = 8 * mm
    top_margin = 10 * mm
    bottom_margin = 10 * mm
    right_margin = 8 * mm

    usable_width = page_width - (left_margin + right_margin)
    usable_height = page_height - (top_margin + bottom_margin)

    cell_width = usable_width / cols
    cell_height = usable_height / rows

    c = canvas.Canvas(str(pdf_path), pagesize=A4)

    total_tags = len(qr_ids)
    num_pages = math.ceil(total_tags / tags_per_page)

    tag_idx = 0
    for page in range(num_pages):
        for row in range(rows):
            for col in range(cols):
                if tag_idx >= total_tags:
                    break

                qr_id = qr_ids[tag_idx]
                tag_url = f"{base_url}/c/{qr_id}"

                # Calculate cell bounding box (origin is bottom-left in ReportLab)
                x = left_margin + col * cell_width
                y = page_height - top_margin - (row + 1) * cell_height

                # Draw subtle tag border / cut mark
                c.setStrokeColorRGB(0.85, 0.85, 0.85)
                c.setLineWidth(0.5)
                c.rect(x + 1, y + 1, cell_width - 2, cell_height - 2)

                # Generate QR code in memory
                img = make_qr_image(tag_url)
                img_buffer = io.BytesIO()
                img.save(img_buffer, format="PNG")
                img_buffer.seek(0)

                # Draw QR code inside cell
                qr_size = min(cell_width - 10, cell_height - 18)
                qr_x = x + (cell_width - qr_size) / 2.0
                qr_y = y + 14  # leave space for label at bottom

                # Use ReportLab's drawImage with PIL ImageReader
                from reportlab.lib.utils import ImageReader
                c.drawImage(ImageReader(img_buffer), qr_x, qr_y, width=qr_size, height=qr_size)

                # Print human-readable short QR ID
                c.setFillColorRGB(0.1, 0.1, 0.1)
                c.setFont("Helvetica-Bold", 7.5)
                c.drawCentredString(x + cell_width / 2.0, y + 4.5, qr_id)

                tag_idx += 1

        c.showPage()

    c.save()
    return pdf_path
