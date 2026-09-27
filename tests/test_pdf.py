import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from app.retrieval.loader import load_documents_from_directory
from app.retrieval.chunker import chunk_text
from app.retrieval.indexer import index_chunks, search_chunks
from app.retrieval.hybrid import hybrid_search
from app.retrieval.rag import ask_documents, index_all_documents, get_document_status


def _create_minimal_pdf(text: str) -> bytes:
    """Create a minimal valid text-based PDF in bytes."""
    stream_content = f"BT\n/F1 12 Tf\n50 700 Td\n({text}) Tj\nET\n".encode("latin1")
    length = len(stream_content)
    pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>endobj\n"
        b"4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
        b"5 0 obj<</Length " + str(length).encode("ascii") + b">>stream\n"
        + stream_content +
        b"endstream\nendobj\n"
        b"xref\n0 6\n0000000000 65535 f \n"
        b"0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000244 00000 n \n0000000318 00000 n \n"
        b"trailer<</Size 6/Root 1 0 R>>\nstartxref\n500\n%%EOF"
    )
    return pdf


class TestPDFIngestion(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.temp_path = Path(self.temp_dir.name)
        self.test_db = self.temp_path / "test_docs.db"
        self.patcher = patch("app.retrieval.indexer.DOCUMENTS_DB_PATH", self.test_db)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.temp_dir.cleanup()

    def test_pdf_loading_and_page_extraction(self):
        pdf_file = self.temp_path / "manual.pdf"
        pdf_file.write_bytes(_create_minimal_pdf("JARVIS Protocol Specification"))

        docs = load_documents_from_directory(self.temp_path)
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["source"], "manual.pdf")
        self.assertIn("JARVIS Protocol Specification", docs[0]["text"])
        self.assertIn("[Page 1]", docs[0]["text"])
        self.assertEqual(docs[0]["page_count"], 1)

    @patch("app.retrieval.indexer.embed_texts")
    def test_pdf_chunking_and_fts_indexing(self, mock_embed_texts):
        mock_embed_texts.return_value = [[0.2, 0.4, 0.6]]
        pdf_file = self.temp_path / "guide.pdf"
        pdf_file.write_bytes(_create_minimal_pdf("Neural Interface Activation Sequence"))

        docs = load_documents_from_directory(self.temp_path)
        self.assertEqual(len(docs), 1)

        chunks = chunk_text(docs[0]["text"], source=docs[0]["source"])
        self.assertTrue(len(chunks) >= 1)

        index_chunks(chunks, source=docs[0]["source"], rel_path="guide.pdf")

        # Query via BM25
        results = search_chunks("Activation")
        self.assertEqual(len(results), 1)
        self.assertIn("Activation Sequence", results[0]["content"])
        self.assertEqual(results[0]["source"], "guide.pdf")

    @patch("app.retrieval.hybrid.semantic_search")
    def test_pdf_retrieval_via_hybrid_search(self, mock_semantic):
        mock_semantic.return_value = []
        pdf_file = self.temp_path / "arch.pdf"
        pdf_file.write_bytes(_create_minimal_pdf("Quantum Core Topology"))

        docs = load_documents_from_directory(self.temp_path)
        chunks = chunk_text(docs[0]["text"], source=docs[0]["source"])
        index_chunks(chunks, source=docs[0]["source"], rel_path="arch.pdf")

        hybrid_results = hybrid_search("Topology", limit=3)
        self.assertEqual(len(hybrid_results), 1)
        self.assertEqual(hybrid_results[0]["source"], "arch.pdf")
        self.assertIn("Quantum Core Topology", hybrid_results[0]["content"])

    def test_corrupted_pdf_handling(self):
        # Create a corrupted file with .pdf extension
        corrupt_file = self.temp_path / "broken.pdf"
        corrupt_file.write_bytes(b"NOT A VALID PDF CONTENT")

        # Create a valid text file in same directory
        txt_file = self.temp_path / "valid.txt"
        txt_file.write_text("Valid plain text document", encoding="utf-8")

        # Loading should not crash and should still load the valid text document
        docs = load_documents_from_directory(self.temp_path)
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["source"], "valid.txt")

    def test_empty_or_no_text_pdf_handling(self):
        import pypdf
        # Create a blank PDF without any text stream
        blank_pdf = self.temp_path / "blank.pdf"
        writer = pypdf.PdfWriter()
        writer.add_blank_page(width=100, height=100)
        with open(blank_pdf, "wb") as f:
            writer.write(f)

        docs = load_documents_from_directory(self.temp_path)
        # Blank PDF has no extractable text -> returns None
        self.assertEqual(len(docs), 0)

    @patch("app.retrieval.indexer.embed_texts")
    def test_mixed_formats_indexing(self, mock_embed_texts):
        mock_embed_texts.return_value = [[0.1, 0.1]]

        (self.temp_path / "doc.txt").write_text("Text file content", encoding="utf-8")
        (self.temp_path / "doc.md").write_text("# Markdown Heading\nMarkdown content", encoding="utf-8")
        (self.temp_path / "doc.pdf").write_bytes(_create_minimal_pdf("PDF Page Text"))

        status_msg = index_all_documents(str(self.temp_path))
        self.assertIn("Indexed 3 documents", status_msg)

        status_report = get_document_status()
        self.assertIn("Indexed Documents: 3", status_report)
        self.assertIn("doc.pdf", status_report)
        self.assertIn("doc.txt", status_report)
        self.assertIn("doc.md", status_report)


if __name__ == "__main__":
    unittest.main()
