"""
Generates scanned-looking PDFs and images from OrgRecords.
Takes the digital PDF, renders it to an image, adds noise/rotation, wraps back as PDF.
Also produces standalone JPG/PNG images for the image_processor tests.
"""

import os
import random
from io import BytesIO

import fitz  # PyMuPDF
from PIL import Image, ImageFilter, ImageEnhance
import numpy as np

from .org_database import OrgRecord
from .pdf_builder import build_digital_pdf


def _add_scan_noise(img: Image.Image) -> Image.Image:
    """Add realistic scan artifacts: slight rotation, noise, blur, contrast shift."""
    # Random slight rotation (-2 to +2 degrees)
    angle = random.uniform(-2.0, 2.0)
    img = img.rotate(angle, fillcolor=(255, 255, 255), expand=False)

    # Convert to numpy for noise
    arr = np.array(img, dtype=np.float32)

    # Add gaussian noise
    noise_level = random.uniform(5, 15)
    noise = np.random.normal(0, noise_level, arr.shape)
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)

    # Slight blur (simulates scan quality)
    if random.random() < 0.5:
        img = img.filter(ImageFilter.GaussianBlur(radius=0.5))

    # Adjust contrast slightly
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(random.uniform(0.85, 1.15))

    # Adjust brightness slightly
    enhancer = ImageEnhance.Brightness(img)
    img = enhancer.enhance(random.uniform(0.90, 1.05))

    return img


def build_scanned_pdf(org: OrgRecord, output_dir: str) -> tuple[str, bytes]:
    """Build a scanned-looking PDF: render digital PDF pages as noisy images, repack as PDF."""
    # First build a clean digital PDF
    _, clean_pdf_bytes = build_digital_pdf(org, output_dir)

    # Open with PyMuPDF and render each page as image
    doc = fitz.open(stream=clean_pdf_bytes, filetype="pdf")
    scanned_images = []

    for page in doc:
        # Render at 150 DPI (lower than 300 to simulate cheap scanner)
        dpi = random.choice([150, 200])
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

        # Add scan noise
        img = _add_scan_noise(img)

        # Convert to grayscale (many scanners produce grayscale)
        if random.random() < 0.7:
            img = img.convert("L").convert("RGB")

        scanned_images.append(img)

    doc.close()

    # Remove the clean PDF (we'll replace it with scanned version)
    clean_files = [f for f in os.listdir(output_dir) if f.startswith(org.id) and f.endswith(".pdf")]
    for f in clean_files:
        os.remove(os.path.join(output_dir, f))

    # Pack images back into a PDF
    safe_name = org.org_name.replace(" ", "_").replace("/", "_")[:40] if org.org_name else org.id
    filename = f"{org.id}_{safe_name}_scan.pdf"
    filepath = os.path.join(output_dir, filename)

    if scanned_images:
        first = scanned_images[0]
        rest = scanned_images[1:] if len(scanned_images) > 1 else []
        first.save(filepath, "PDF", save_all=True, append_images=rest, resolution=150)

    # Read bytes back
    with open(filepath, "rb") as f:
        pdf_bytes = f.read()

    return filepath, pdf_bytes


def build_scanned_image(org: OrgRecord, output_dir: str) -> tuple[str, bytes]:
    """Build a scanned image (JPG or PNG) - simulates a photographed/scanned letter."""
    # Build digital PDF first, render first page as image
    _, clean_pdf_bytes = build_digital_pdf(org, output_dir)

    doc = fitz.open(stream=clean_pdf_bytes, filetype="pdf")
    page = doc[0]
    dpi = random.choice([150, 200, 250])
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    doc.close()

    # Add heavier noise for photos
    img = _add_scan_noise(img)

    # Sometimes add perspective-like effect (slight crop)
    if random.random() < 0.3:
        w, h = img.size
        crop_px = random.randint(5, 20)
        img = img.crop((crop_px, crop_px, w - crop_px, h - crop_px))

    # Remove the temp clean PDF
    clean_files = [f for f in os.listdir(output_dir) if f.startswith(org.id) and f.endswith(".pdf")]
    for f in clean_files:
        os.remove(os.path.join(output_dir, f))

    safe_name = org.org_name.replace(" ", "_").replace("/", "_")[:40] if org.org_name else org.id
    ext = random.choice(["jpg", "png"])
    filename = f"{org.id}_{safe_name}_photo.{ext}"
    filepath = os.path.join(output_dir, filename)

    if ext == "jpg":
        quality = random.randint(60, 85)
        img.save(filepath, "JPEG", quality=quality)
    else:
        img.save(filepath, "PNG")

    with open(filepath, "rb") as f:
        img_bytes = f.read()

    return filepath, img_bytes
