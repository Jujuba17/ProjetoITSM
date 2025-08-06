# src/utils/text_utils.py
"""
Funções utilitárias para manipulação e normalização de texto.
"""
import re

def strip_html_tags(html_string: str) -> str:
    """Remove tags HTML de uma string."""
    if not html_string:
        return ""
    return re.sub(r'<[^>]*>', '', html_string)

def normalize_text(text: str) -> str:
    """Normaliza o texto para uma comparação mais robusta."""
    if not text:
        return ""
    text_no_punct = re.sub(r'[^\w\s]', '', text)
    return re.sub(r'\s+', ' ', text_no_punct).strip().lower()