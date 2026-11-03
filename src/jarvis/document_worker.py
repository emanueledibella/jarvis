"""Bounded, separate-process parsing. This module never loads Jarvis credentials."""
from __future__ import annotations

import base64
import io
import json
import os
import shutil
import subprocess
import sys
import warnings
import zipfile
from pathlib import Path

from defusedxml import ElementTree
from PIL import Image, ImageOps
from pypdf import PdfReader

MAX_BYTES = 3_000_000
MAX_TEXT = 300_000
MAX_PAGES = 30


def image_page(image, index):
    if image.width * image.height > 20_000_000:
        raise ValueError("Image exceeds 20 million pixels.")
    image = ImageOps.exif_transpose(image).convert("RGB")
    image.thumbnail((1800, 1800))
    tesseract = shutil.which("tesseract")
    if tesseract:
        output = io.BytesIO()
        image.save(output, format="PNG")
        result = subprocess.run([tesseract, "stdin", "stdout", "-l", "eng", "--psm", "3"],
                                input=output.getvalue(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10, check=False)
        if result.returncode == 0:
            return {"part": index, "text": result.stdout[:50000].decode("utf-8", errors="replace"), "method": "local_ocr", "confidence": None}
    for _ in range(4):
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=75)
        if len(output.getvalue()) <= 280000:
            return {"part": index, "text": "", "method": "ocr_required", "image": base64.b64encode(output.getvalue()).decode()}
        image.thumbnail((max(1, int(image.width * .7)), max(1, int(image.height * .7))))
    raise ValueError("OCR image exceeds its size limit.")


def extract(raw: bytes, extension: str):
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("Choose a file of at most 3 MB.")
    pages, warnings_out = [], []
    if extension in {".txt", ".md", ".csv"}:
        text = raw.decode("utf-8-sig")
        if "\x00" in text:
            raise ValueError("Only UTF-8 text files are supported.")
        lines = text.splitlines()
        pages = [{"part": i // 80 + 1, "text": "\n".join(lines[i:i + 80]), "method": "text",
                  "line_start": i + 1, "line_end": min(i + 80, len(lines))} for i in range(0, len(lines), 80)]
    elif extension == ".docx":
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) > 1000 or sum(x.file_size for x in entries) > 12_000_000:
                raise ValueError("Document archive exceeds its expansion limit.")
            if any("vbaproject" in x.filename.casefold() or x.flag_bits & 1 or x.file_size > 5_000_000 for x in entries):
                raise ValueError("Encrypted or macro documents are not supported.")
            xml = archive.read("word/document.xml")
            if b"\x00" in xml or b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
                raise ValueError("XML entities are not supported.")
            root = ElementTree.fromstring(xml)
            ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
            paragraphs = ["".join(node.itertext()) for node in root.iter(ns + "p")]
            pages = [{"part": i // 40 + 1, "text": "\n".join(paragraphs[i:i + 40]), "method": "paragraphs",
                      "paragraph_start": i + 1, "paragraph_end": min(i + 40, len(paragraphs))} for i in range(0, len(paragraphs), 40)]
    elif extension == ".pdf":
        if not raw.startswith(b"%PDF-"):
            raise ValueError("The file does not have a PDF signature.")
        reader = PdfReader(io.BytesIO(raw), strict=True)
        if reader.is_encrypted:
            raise ValueError("Encrypted PDFs are not supported.")
        root = reader.trailer["/Root"]
        if "/OpenAction" in root or "/AA" in root or "/JavaScript" in root.get("/Names", {}):
            raise ValueError("Active PDF content is not supported.")
        if len(reader.pages) > MAX_PAGES:
            raise ValueError("Split PDFs into at most 30 pages.")
        rendered = None
        try:
            for index, page in enumerate(reader.pages):
                if "/AA" in page:
                    raise ValueError("Active PDF pages are not supported.")
                content = page.get_contents()
                if content is not None and len(content.get_data()) > 5_000_000:
                    raise ValueError("A PDF page exceeds its content-stream limit.")
                text = page.extract_text() or ""
                if text.strip():
                    pages.append({"part": index + 1, "text": text[:50000], "method": "pdf_text", "truncated": len(text) > 50000})
                else:
                    import pypdfium2 as pdfium
                    if rendered is None:
                        rendered = pdfium.PdfDocument(raw)
                    pdf_page = rendered[index]
                    width, height = pdf_page.get_size()
                    scale = min(2.5, 1800 / max(width, height))
                    bitmap = pdf_page.render(scale=scale)
                    pages.append(image_page(bitmap.to_pil(), index + 1))
                    bitmap.close()
                    pdf_page.close()
        finally:
            if rendered:
                rendered.close()
        warnings_out.append("Text extraction does not establish visual layout or image semantics.")
    elif extension in {".png", ".jpg", ".jpeg"}:
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(raw)) as image:
            if image.format != ("PNG" if extension == ".png" else "JPEG"):
                raise ValueError("Only PNG and JPEG images are supported.")
            pages = [image_page(image, 1)]
    else:
        raise ValueError("Unsupported document type.")
    if len(pages) > 300 or sum(len(x["text"]) for x in pages) > MAX_TEXT:
        raise ValueError("Document text exceeds its extraction limit.")
    return {"parts": pages, "warnings": warnings_out, "part_count": len(pages)}


def main():
    os.umask(0o077)
    try:
        if os.name != "nt":
            import resource
            for kind, target in ((resource.RLIMIT_CPU, 18), (resource.RLIMIT_AS, 1_500_000_000), (resource.RLIMIT_FSIZE, 4_000_000)):
                _, hard = resource.getrlimit(kind)
                limit = min(target, hard) if hard != resource.RLIM_INFINITY else target
                try:
                    resource.setrlimit(kind, (limit, limit))
                except (OSError, ValueError):
                    if kind != resource.RLIMIT_AS:
                        raise
        payload = json.loads(sys.stdin.buffer.read(4_100_000))
        extension = Path(payload["name"]).suffix.casefold()
        raw = base64.b64decode(payload["content"], validate=True)
        result = extract(raw, extension)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as error:
        safe = str(error) if isinstance(error, (ValueError, UnicodeError, zipfile.BadZipFile)) else "Document parsing failed."
        print(json.dumps({"error": safe[:300]}))


if __name__ == "__main__":
    main()
