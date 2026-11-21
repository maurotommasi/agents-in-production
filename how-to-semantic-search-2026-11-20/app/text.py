"""Text chunking.

Long documents are split into overlapping chunks before embedding.
A chunk is the unit that gets one vector and the unit returned by
search, so chunk size is a quality decision: too big and the vector
averages many topics, too small and each chunk loses context.
800 characters with 100 characters of overlap is a solid default
for help centre and knowledge base text.
"""


def chunk_text(text: str, chunk_chars: int = 800, overlap: int = 100) -> list[str]:
    text = " ".join(text.split())
    if len(text) <= chunk_chars:
        return [text] if text else []
    chunks: list[str] = []
    step = max(1, chunk_chars - overlap)
    start = 0
    while start < len(text):
        end = start + chunk_chars
        piece = text[start:end]
        # Prefer to break on a sentence or word boundary near the end.
        if end < len(text):
            cut = max(piece.rfind(". "), piece.rfind(" "))
            if cut > chunk_chars * 0.5:
                piece = piece[: cut + 1]
                end = start + cut + 1
        chunks.append(piece.strip())
        if end >= len(text):
            break
        start = start + step
    return [c for c in chunks if c]
