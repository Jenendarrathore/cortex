import re
from core.config import settings
from core.text_utils import count_tokens, strip_markdown


def _token_count(text: str) -> int:
    return count_tokens(strip_markdown(text))


def _split_long(text: str, heading: str, start_index: int) -> list:
    """Sliding window split for oversized sections.

    Tracks cumulative char count per word instead of rebuilding the full
    candidate string on every iteration — O(n) not O(n²).
    """
    max_tokens = settings.chunk_max_tokens
    words = text.split(" ")
    word_lens = [len(w) for w in words]
    chunks = []
    sub_idx = 0
    lo = 0

    while lo < len(words):
        char_count = 0
        hi = lo
        while hi < len(words):
            # +1 for the space between words (not before the first)
            next_chars = word_lens[hi] + (1 if hi > lo else 0)
            if (char_count + next_chars) // 4 > max_tokens:
                break
            char_count += next_chars
            hi += 1

        hi = max(lo + 1, hi)  # always advance at least one word
        chunk_text = " ".join(words[lo:hi]).strip()
        if heading:
            chunk_text = f"{heading}\n\n{chunk_text}"
        if chunk_text:
            chunks.append({
                "text": chunk_text,
                "heading": heading,
                "chunk_index": start_index + sub_idx,
                "token_count": _token_count(chunk_text),
            })
            sub_idx += 1
        if hi >= len(words):
            break
        # Step back ~overlap_chars / 4 words (same approximation as count_tokens)
        overlap_words = max(1, settings.chunk_overlap_chars // 4)
        lo = hi - overlap_words

    return chunks


def chunk_by_headings(content: str) -> list:
    """
    Split markdown content on heading boundaries (# / ## / ###).
    Each section becomes a chunk; oversized sections are further split
    with overlap. Tiny sections (<50 tokens) are merged with the next.
    """
    heading_pattern = re.compile(r'^(#{1,3} .+)$', re.MULTILINE)
    parts = heading_pattern.split(content)

    # parts alternates: [pre-heading text, heading, section, heading, section, ...]
    sections = []
    current_heading = None
    buffer = []

    for part in parts:
        if heading_pattern.match(part):
            if buffer:
                sections.append((current_heading, "\n".join(buffer).strip()))
            current_heading = part.strip()
            buffer = []
        else:
            buffer.append(part)

    if buffer:
        sections.append((current_heading, "\n".join(buffer).strip()))

    chunks = []
    chunk_index = 0
    pending_heading = None
    pending_text = ""

    for heading, text in sections:
        if not text:
            continue

        # Merge tiny sections into pending buffer
        if _token_count(text) < 50:
            pending_heading = pending_heading or heading
            pending_text += f"\n\n{heading or ''}\n{text}" if heading else f"\n\n{text}"
            continue

        # Flush pending buffer first
        if pending_text.strip():
            full_text = (
                f"{pending_heading}\n\n{pending_text.strip()}"
                if pending_heading
                else pending_text.strip()
            )
            chunks.append({
                "text": full_text,
                "heading": pending_heading,
                "chunk_index": chunk_index,
                "token_count": _token_count(full_text),
            })
            chunk_index += 1
            pending_heading = None
            pending_text = ""

        full_text = f"{heading}\n\n{text}" if heading else text
        if _token_count(full_text) <= settings.chunk_max_tokens:
            chunks.append({
                "text": full_text.strip(),
                "heading": heading,
                "chunk_index": chunk_index,
                "token_count": _token_count(full_text),
            })
            chunk_index += 1
        else:
            sub_chunks = _split_long(text, heading, chunk_index)
            chunks.extend(sub_chunks)
            chunk_index += len(sub_chunks)

    # Flush any remaining pending
    if pending_text.strip():
        full_text = (
            f"{pending_heading}\n\n{pending_text.strip()}"
            if pending_heading
            else pending_text.strip()
        )
        chunks.append({
            "text": full_text,
            "heading": pending_heading,
            "chunk_index": chunk_index,
            "token_count": _token_count(full_text),
        })

    return chunks
