"""Tests for document upload extraction in translation router."""

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi import HTTPException

from api.routers.readme_translate import (
    _extract_translation_document_text,
    _safe_translation_filename,
    TRANSLATION_DOCUMENT_EXTENSIONS,
)


def _minimal_docx(paragraphs: list[str]) -> bytes:
    """Build a minimal DOCX package with document.xml only."""
    xml_paragraphs = "".join(
        f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"
        for text in paragraphs
    )
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{xml_paragraphs}</w:body>"
        "</w:document>"
    )
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


def test_translation_document_extensions_cover_requested_formats() -> None:
    assert {".md", ".markdown", ".txt", ".html", ".htm", ".docx", ".pdf"} <= TRANSLATION_DOCUMENT_EXTENSIONS


def test_extract_translation_document_text_from_plain_text() -> None:
    text = _extract_translation_document_text("notes.txt", "Привет\n\nмир".encode("utf-8"))

    assert text == "Привет\n\nмир"


def test_extract_translation_document_text_from_html_strips_markup_and_scripts() -> None:
    html = b"<html><body><h1>Title</h1><script>bad()</script><p>Hello <b>world</b></p></body></html>"

    text = _extract_translation_document_text("page.html", html)

    assert "Title" in text
    assert "Hello" in text
    assert "world" in text
    assert "bad()" not in text
    assert "<h1>" not in text


def test_extract_translation_document_text_from_docx() -> None:
    content = _minimal_docx(["Первый абзац", "Второй абзац"])

    text = _extract_translation_document_text("document.docx", content)

    assert "Первый абзац" in text
    assert "Второй абзац" in text


def test_safe_translation_filename_rejects_unsupported_extension() -> None:
    upload = type("Upload", (), {"filename": "payload.exe"})()

    with pytest.raises(HTTPException) as exc_info:
        _safe_translation_filename(upload)

    assert exc_info.value.status_code == 400
    assert "Формат документа не поддерживается" in exc_info.value.detail
