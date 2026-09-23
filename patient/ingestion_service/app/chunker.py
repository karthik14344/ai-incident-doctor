from typing import List, Dict, Any

def create_chunks(pages_data: List[Dict[str, Any]], chunk_size: int = 800, chunk_overlap: int = 100) -> List[Dict[str, Any]]:
    """
    Chunks page text with specified chunk size and overlap.
    Preserves page source mapping.
    """
    chunks = []
    chunk_index = 0

    for page_info in pages_data:
        page_num = page_info["page"]
        text = page_info["text"]

        if not text:
            continue

        start = 0
        text_len = len(text)

        while start < text_len:
            end = min(start + chunk_size, text_len)
            chunk_text = text[start:end].strip()

            if chunk_text:
                chunk_index += 1
                token_count = len(chunk_text.split())
                chunks.append({
                    "chunk_index": chunk_index,
                    "page_number": page_num,
                    "text": chunk_text,
                    "token_count": token_count
                })

            if end >= text_len:
                break
            
            start += max(1, chunk_size - chunk_overlap)

    return chunks
