from pathlib import Path
from typing import List, Dict, Any, Optional

from app.utils.logger import logger

SUPPORTED_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".py",
    ".json",
    ".csv",
    ".log",
    ".yaml",
    ".yml",
    ".pdf",
}


def _load_pdf_file(file_path: Path, dir_path: Path) -> Optional[Dict[str, Any]]:
    """
    Extract text from a text-based PDF file page by page using pypdf.
    Handles corrupted, encrypted, empty, and scanned PDFs gracefully.
    """
    try:
        import pypdf
    except ImportError:
        logger.warning("pypdf is not installed. PDF ingestion is unavailable.")
        return None

    try:
        reader = pypdf.PdfReader(str(file_path))

        if reader.is_encrypted:
            try:
                # Try empty password for default-encrypted PDFs
                reader.decrypt("")
            except Exception:
                logger.warning(f"Skipping password-protected PDF: {file_path.name}")
                return None

        if len(reader.pages) == 0:
            logger.warning(f"PDF file has 0 pages: {file_path.name}")
            return None

        pages_text: List[str] = []
        for page_num, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text()
                if text and text.strip():
                    pages_text.append(f"--- [Page {page_num}] ---\n{text.strip()}")
            except Exception as e:
                logger.warning(f"Error extracting page {page_num} in PDF '{file_path.name}': {e}")

        if not pages_text:
            logger.warning(f"No extractable text found in PDF (may be scanned/image-only): {file_path.name}")
            return None

        combined_text = "\n\n".join(pages_text)
        return {
            "source": file_path.name,
            "rel_path": str(file_path.relative_to(dir_path)),
            "full_path": str(file_path),
            "text": combined_text,
            "size": len(combined_text),
            "page_count": len(reader.pages),
        }

    except Exception as e:
        logger.warning(f"Failed to load or parse PDF '{file_path.name}': {e}")
        return None


def load_documents_from_directory(dir_path: Path) -> List[Dict[str, Any]]:
    """Load text and PDF documents from a directory."""
    documents = []
    if not dir_path.exists() or not dir_path.is_dir():
        return documents

    for file_path in dir_path.rglob("*"):
        if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
            if file_path.suffix.lower() == ".pdf":
                doc = _load_pdf_file(file_path, dir_path)
                if doc:
                    documents.append(doc)
            else:
                try:
                    content = file_path.read_text(encoding="utf-8", errors="replace")
                    if content.strip():
                        documents.append({
                            "source": file_path.name,
                            "rel_path": str(file_path.relative_to(dir_path)),
                            "full_path": str(file_path),
                            "text": content,
                            "size": len(content),
                        })
                except Exception as e:
                    logger.warning(f"Error reading file '{file_path.name}': {e}")

    return documents
