"""文档解析模块（FR-A1）+ 内容哈希去重（FR-A5）。

支持 ``.pdf`` / ``.docx`` / ``.txt`` / ``.md`` 四类文件，统一解析成
带「页码或章节」标签的 :class:`PageText` 列表，供分块模块消费。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import List, Union

SUPPORTED_SUFFIXES = (".pdf", ".docx", ".txt", ".md")

PathLike = Union[str, Path]


@dataclass
class PageText:
    """一段带来源标签的正文。"""

    text: str
    page: str = "全文"  # PDF 为「第 N 页」，DOCX 为章节标题，TXT 为「全文」


class DocumentParseError(RuntimeError):
    """文档解析失败（格式不支持 / 文件损坏 / 依赖缺失）。"""


def file_sha256(path: PathLike, chunk_size: int = 1 << 20) -> str:
    """计算文件内容 SHA-256，用于 FR-A5 的重复上传覆盖判断。"""
    digest = hashlib.sha256()
    with open(path, "rb") as fp:
        for block in iter(lambda: fp.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_pdf(path: PathLike) -> List[PageText]:
    """解析 PDF，逐页返回文本（保留真实页码）。"""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise DocumentParseError("缺少依赖 pypdf，请执行 pip install pypdf") from exc

    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:
                raise DocumentParseError(f"PDF 已加密，无法解析: {exc}") from exc
    except DocumentParseError:
        raise
    except Exception as exc:
        raise DocumentParseError(f"PDF 解析失败: {exc}") from exc

    pages: List[PageText] = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            raw = page.extract_text() or ""
        except Exception:
            raw = ""
        raw = raw.strip()
        if raw:
            pages.append(PageText(text=raw, page=f"第 {i} 页"))
    if not pages:
        raise DocumentParseError("PDF 未能提取到任何文本（可能是扫描版，需先做 OCR）")
    return pages


_HEADING_STYLES = ("heading", "标题", "title")


def load_docx(path: PathLike) -> List[PageText]:
    """解析 DOCX。

    python-docx 拿不到真实页码，因此按**标题样式**切分成章节，
    ``page`` 字段记录章节标题（找不到标题时退化为「第 N 段」）。
    """
    try:
        import docx
    except ImportError as exc:  # pragma: no cover
        raise DocumentParseError("缺少依赖 python-docx，请执行 pip install python-docx") from exc

    try:
        document = docx.Document(str(path))
    except Exception as exc:
        raise DocumentParseError(f"DOCX 解析失败: {exc}") from exc

    sections: List[PageText] = []
    current_title = "正文"
    buffer: List[str] = []

    def flush() -> None:
        text = "\n".join(buffer).strip()
        if text:
            sections.append(PageText(text=text, page=current_title))
        buffer.clear()

    for para in document.paragraphs:
        text = (para.text or "").strip()
        if not text:
            continue
        style = (para.style.name or "").lower() if para.style is not None else ""
        is_heading = any(flag in style for flag in _HEADING_STYLES)
        if is_heading:
            flush()
            current_title = text[:60]
            buffer.append(text)
        else:
            buffer.append(text)

    for table in document.tables:
        rows = []
        for row in table.rows:
            cells = [(cell.text or "").strip() for cell in row.cells]
            if any(cells):
                rows.append("  ".join(c for c in cells if c))
        if rows:
            flush()
            current_title = "表格"
            buffer.extend(rows)

    flush()
    if not sections:
        raise DocumentParseError("DOCX 未能提取到任何文本")
    return sections


def load_txt(path: PathLike) -> List[PageText]:
    """解析 TXT / Markdown，按空行分页（每页约 800 字，仅用于生成 page 标签）。"""
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk", "big5", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover
        raise DocumentParseError("无法识别文本编码")

    text = text.strip()
    if not text:
        raise DocumentParseError("文本文件为空")

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    pages: List[PageText] = []
    buffer: List[str] = []
    size = 0
    for para in paragraphs:
        buffer.append(para)
        size += len(para)
        if size >= 800:
            pages.append(PageText(text="\n\n".join(buffer), page=f"第 {len(pages) + 1} 段"))
            buffer, size = [], 0
    if buffer:
        pages.append(PageText(text="\n\n".join(buffer), page=f"第 {len(pages) + 1} 段"))
    return pages


def load_document(path: PathLike) -> List[PageText]:
    """按扩展名分派到对应解析器。"""
    p = Path(path)
    if not p.exists():
        raise DocumentParseError(f"文件不存在: {p}")
    suffix = p.suffix.lower()
    if suffix == ".pdf":
        return load_pdf(p)
    if suffix == ".docx":
        return load_docx(p)
    if suffix in (".txt", ".md"):
        return load_txt(p)
    raise DocumentParseError(
        f"不支持的文件类型: {suffix or '(无扩展名)'}，仅支持 {list(SUPPORTED_SUFFIXES)}"
    )


def pages_to_plain_text(pages: List[PageText]) -> str:
    return "\n\n".join(p.text for p in pages)