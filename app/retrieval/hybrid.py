from typing import List, Dict, Any, Optional, Tuple

from app.retrieval.indexer import search_chunks, semantic_search
from app.utils.logger import logger


def hybrid_search(
    query: str,
    limit: int = 5,
    candidate_limit: int = 10,
    rrf_k: int = 60,
    model: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Perform hybrid retrieval combining BM25 lexical search and semantic embedding search
    using Reciprocal Rank Fusion (RRF).

    Formula:
        RRF_score(d) = sum(1.0 / (rrf_k + rank_i(d)))

    Gracefully degrades if semantic search fails or returns empty, falling back to lexical search.
    """
    if not query or not query.strip():
        return []

    # 1. Retrieve Lexical (BM25) candidates
    try:
        lexical_candidates = search_chunks(query, top_k=candidate_limit)
    except Exception as e:
        logger.warning(f"Lexical BM25 search failed during hybrid retrieval: {e}")
        lexical_candidates = []

    # 2. Retrieve Semantic embedding candidates
    try:
        semantic_candidates = semantic_search(query, limit=candidate_limit, model=model)
    except Exception as e:
        logger.warning(f"Semantic search failed during hybrid retrieval: {e}")
        semantic_candidates = []

    # If both return nothing, return empty
    if not lexical_candidates and not semantic_candidates:
        return []

    fused: Dict[Tuple[str, int], Dict[str, Any]] = {}

    # Score Lexical candidates
    for rank, chunk in enumerate(lexical_candidates, start=1):
        key = (chunk.get("source", ""), chunk.get("chunk_index", 0))
        rrf_contrib = 1.0 / (rrf_k + rank)
        fused[key] = {
            "chunk_id": f"{chunk.get('source', '')}:{chunk.get('chunk_index', 0)}",
            "source": chunk.get("source", ""),
            "rel_path": chunk.get("rel_path", ""),
            "chunk_index": chunk.get("chunk_index", 0),
            "content": chunk.get("content", ""),
            "rrf_score": rrf_contrib,
            "lexical_rank": rank,
            "semantic_rank": None,
            "lexical_score": chunk.get("score"),
            "semantic_score": None,
        }

    # Score Semantic candidates & Fuse
    for rank, chunk in enumerate(semantic_candidates, start=1):
        key = (chunk.get("source", ""), chunk.get("chunk_index", 0))
        rrf_contrib = 1.0 / (rrf_k + rank)
        if key in fused:
            fused[key]["rrf_score"] += rrf_contrib
            fused[key]["semantic_rank"] = rank
            fused[key]["semantic_score"] = chunk.get("score")
            # If content was empty in lexical for any reason, fill it
            if not fused[key]["content"] and chunk.get("content"):
                fused[key]["content"] = chunk.get("content")
        else:
            fused[key] = {
                "chunk_id": f"{chunk.get('source', '')}:{chunk.get('chunk_index', 0)}",
                "source": chunk.get("source", ""),
                "rel_path": chunk.get("rel_path", ""),
                "chunk_index": chunk.get("chunk_index", 0),
                "content": chunk.get("content", ""),
                "rrf_score": rrf_contrib,
                "lexical_rank": None,
                "semantic_rank": rank,
                "lexical_score": None,
                "semantic_score": chunk.get("score"),
            }

    # Format final ranked results
    results: List[Dict[str, Any]] = []
    for item in fused.values():
        results.append({
            "chunk_id": item["chunk_id"],
            "source": item["source"],
            "rel_path": item["rel_path"],
            "chunk_index": item["chunk_index"],
            "content": item["content"],
            "score": round(item["rrf_score"], 6),
            "lexical_rank": item["lexical_rank"],
            "semantic_rank": item["semantic_rank"],
            "lexical_score": item["lexical_score"],
            "semantic_score": item["semantic_score"],
        })

    # Sort descending by RRF score
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]
