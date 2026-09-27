from typing import List, Dict, Any


def chunk_text(
    text: str,
    source: str,
    chunk_size: int = 500,
    chunk_overlap: int = 100
) -> List[Dict[str, Any]]:
    """
    Split text into overlapping chunks while trying to preserve sentence/line boundaries.
    """
    if not text:
        return []

    lines = text.splitlines(keepends=True)
    chunks: List[Dict[str, Any]] = []

    current_chunk: List[str] = []
    current_length = 0
    chunk_index = 0

    for line in lines:
        current_chunk.append(line)
        current_length += len(line)

        if current_length >= chunk_size:
            chunk_content = "".join(current_chunk).strip()
            if chunk_content:
                chunks.append({
                    "source": source,
                    "chunk_index": chunk_index,
                    "content": chunk_content,
                    "char_count": len(chunk_content),
                })
                chunk_index += 1

            # Prepare overlap
            overlap_buffer: List[str] = []
            overlap_len = 0
            for l in reversed(current_chunk):
                overlap_buffer.insert(0, l)
                overlap_len += len(l)
                if overlap_len >= chunk_overlap:
                    break

            current_chunk = overlap_buffer
            current_length = overlap_len

    # Add final remaining chunk
    if current_chunk:
        remaining_content = "".join(current_chunk).strip()
        if remaining_content and (not chunks or chunks[-1]["content"] != remaining_content):
            chunks.append({
                "source": source,
                "chunk_index": chunk_index,
                "content": remaining_content,
                "char_count": len(remaining_content),
            })

    return chunks
