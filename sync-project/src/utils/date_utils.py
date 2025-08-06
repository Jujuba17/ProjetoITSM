# src/utils/date_utils.py
"""
Funções utilitárias para parsing e manipulação de datas.
"""
from datetime import datetime, timezone

def parse_datetime(datetime_str: str):
    """
    Converte uma string de data/hora (formato ISO 8601) para um objeto datetime
    do Python com timezone (UTC).
    """
    if not datetime_str:
        return None
    normalized_str = str(datetime_str).replace('Z', '+00:00')
    try:
        return datetime.fromisoformat(normalized_str).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None