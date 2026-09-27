from pathlib import Path
from typing import Optional, List, Dict, Any

from app.config.settings import DOCUMENTS_DIR, OLLAMA_EMBED_MODEL
from app.retrieval.loader import load_documents_from_directory
from app.retrieval.chunker import chunk_text
from app.retrieval.indexer import (
    index_chunks,
    search_chunks,
    semantic_search,
    get_index_stats,
)
from app.retrieval.hybrid import hybrid_search
from app.utils.logger import logger


def index_all_documents(
    directory: Optional[str] = None,
    generate_embeddings: bool = True,
    model: Optional[str] = None,
) -> str:
    """Load, chunk, and index all supported documents from the documents directory."""
    target_dir = Path(directory).resolve() if directory else DOCUMENTS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    docs = load_documents_from_directory(target_dir)
    if not docs:
        return f"No documents found in {target_dir}. Place .txt, .md, or .pdf files there and try again."

    total_chunks = 0
    for doc in docs:
        chunks = chunk_text(doc["text"], source=doc["source"])
        if chunks:
            index_chunks(
                chunks,
                source=doc["source"],
                rel_path=doc["rel_path"],
                generate_embeddings=generate_embeddings,
                model=model,
            )
            total_chunks += len(chunks)

    logger.info(f"Indexed {len(docs)} documents ({total_chunks} chunks)")
    return f"Indexed {len(docs)} documents ({total_chunks} chunks total) from {target_dir.name}."


def get_document_status() -> str:
    """Return status of the document index including lexical and semantic stats."""
    stats = get_index_stats()
    file_count = stats["file_count"]
    chunk_count = stats["chunk_count"]
    embedded_chunks = stats.get("embedded_chunk_count", 0)
    active_model = stats.get("active_embed_model", OLLAMA_EMBED_MODEL)

    if file_count == 0:
        return f"Document store is empty. Place files in '{DOCUMENTS_DIR}' and run 'index documents'."

    lines = [
        f"Indexed Documents: {file_count}",
        f"Lexical Chunks: {chunk_count}",
        f"Embedded Chunks: {embedded_chunks} (model: {active_model})",
        "Files:",
    ]
    for f in stats["files"]:
        lines.append(f"  - {f['source']} ({f['chunks']} chunks, indexed: {f['indexed_at']})")

    return "\n".join(lines)


def ask_documents(query: str, brain=None, top_k: int = 3) -> str:
    """
    Search indexed documents for relevant chunks and formulate an answer.
    Uses hybrid retrieval (BM25 + Semantic Search + RRF) for grounded document Q&A.
    If brain is provided, uses local LLM to synthesize the response.
    """
    if not query.strip():
        return "Please specify a question or topic to search documents for."

    chunks = hybrid_search(query, limit=top_k)
    if not chunks:
        return "No relevant information found in the indexed documents."

    # Build cited context
    context_blocks = []
    sources = set()
    for c in chunks:
        sources.add(c["source"])
        context_blocks.append(f"[{c['source']} | Chunk {c['chunk_index']}]:\n{c['content']}")

    combined_context = "\n\n".join(context_blocks)

    if brain is None:
        # Fallback to direct excerpts if brain is not provided
        output = [f"Found relevant information in: {', '.join(sources)}\n"]
        for c in chunks:
            output.append(f"--- From {c['source']} (relevance score: {c['score']}) ---")
            output.append(c["content"])
            output.append("")
        return "\n".join(output)

    prompt = f"""You are answering a question based ONLY on the following retrieved document excerpts.
Do not invent facts or cite documents that are not in the context.

Retrieved Context:
{combined_context}

Question:
{query}

Answer concisely with citations to the document names provided:"""

    try:
        response = brain.ask(prompt)
        return response
    except Exception as error:
        logger.error(f"Error querying LLM during ask_documents: {error}")
        # Fall back to showing excerpts
        return f"Found relevant information in {', '.join(sources)}:\n\n{combined_context}"
