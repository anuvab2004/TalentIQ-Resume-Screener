# src package initialization
import re


def clean_doubled_text(text: str) -> str:
    """Repair doubled-letter artifacts caused by PDF shadow-stroke rendering
    (e.g., 'EEDDUUCCAATTIIOONN' -> 'EDUCATION')."""
    if not text:
        return ""

    def _fix_word(match):
        w = match.group(0)
        if len(w) >= 6 and len(w) % 2 == 0:
            if all(w[i].lower() == w[i + 1].lower() for i in range(0, len(w), 2)):
                return "".join(w[i] for i in range(0, len(w), 2))
        return w

    return re.sub(r"\b[A-Za-z]{6,}\b", _fix_word, text)
