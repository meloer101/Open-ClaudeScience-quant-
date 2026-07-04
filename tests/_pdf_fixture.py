"""Build minimal text-bearing PDFs in-memory for literature tests, so no
external fixture files, reportlab, or network are needed. pypdf can extract the
text placed via Tj operators in the content streams."""
from __future__ import annotations

import io


def make_text_pdf(pages_lines: list[list[str]]) -> bytes:
    """pages_lines: one list of text lines per page. Returns PDF bytes whose
    pages pypdf.extract_text() reproduces line by line."""
    contents: list[str] = []
    for lines in pages_lines:
        parts = ["BT", "/F1 12 Tf", "72 720 Td"]
        for index, line in enumerate(lines):
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            if index > 0:
                parts.append("0 -16 Td")
            parts.append(f"({escaped}) Tj")
        parts.append("ET")
        contents.append("\n".join(parts))

    n_pages = len(pages_lines)
    page_ids: list[int] = []
    content_ids: list[int] = []
    next_id = 4
    for _ in range(n_pages):
        page_ids.append(next_id)
        next_id += 1
        content_ids.append(next_id)
        next_id += 1

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}

    def write_obj(obj_id: int, body: bytes) -> None:
        offsets[obj_id] = out.tell()
        out.write(f"{obj_id} 0 obj\n".encode() + body + b"\nendobj\n")

    write_obj(1, b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    write_obj(2, f"<< /Type /Pages /Count {n_pages} /Kids [{kids}] >>".encode())
    write_obj(3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for pid, cid, content in zip(page_ids, content_ids, contents):
        write_obj(
            pid,
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {cid} 0 R >>"
            ).encode(),
        )
        content_bytes = content.encode()
        write_obj(cid, f"<< /Length {len(content_bytes)} >>\nstream\n".encode() + content_bytes + b"\nendstream")

    xref_pos = out.tell()
    total = next_id
    out.write(f"xref\n0 {total}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for i in range(1, total):
        out.write(f"{offsets.get(i, 0):010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {total} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF".encode())
    return out.getvalue()
