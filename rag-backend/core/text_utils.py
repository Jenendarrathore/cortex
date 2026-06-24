import re


def count_tokens(text: str) -> int:
    # ~4 chars per token is a good-enough approximation for chunking.
    # The embed model (nomic-embed-text) uses a LLaMA BPE tokenizer, not BERT —
    # loading bert-base-uncased produces systematically wrong counts.
    return max(1, len(text) // 4)


def strip_markdown(text: str) -> str:
    # Fenced code blocks → keep content, drop fences
    text = re.sub(r'```[^\n]*\n([\s\S]*?)```', r'\1', text)
    # Inline code → keep content
    text = re.sub(r'`([^`]+)`', r'\1', text)
    # Images → drop entirely
    text = re.sub(r'!\[[^\]]*\]\([^\)]*\)', '', text)
    # Links → keep link text
    text = re.sub(r'\[([^\]]+)\]\([^\)]*\)', r'\1', text)
    # Headings → plain text
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # Bold + italic (*** / ** / *)
    text = re.sub(r'\*{1,3}([^*\n]+)\*{1,3}', r'\1', text)
    # Underscore bold + italic
    text = re.sub(r'_{1,3}([^_\n]+)_{1,3}', r'\1', text)
    # Blockquotes
    text = re.sub(r'^>\s?', '', text, flags=re.MULTILINE)
    # Horizontal rules
    text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
    # HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Collapse excess blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()
