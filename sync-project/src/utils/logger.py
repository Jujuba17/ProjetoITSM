# src/utils/logger.py
"""
Módulo de logging centralizado com suporte a níveis.
"""
import threading

# Usamos um lock para garantir que o nível de log seja thread-safe,
# embora neste design sequencial não seja estritamente necessário, é uma boa prática.
_log_config = threading.local()
_log_config.level = 'INFO' # Nível padrão

LOG_LEVELS = {
    'DEBUG': 3,
    'INFO': 2,
    'WARNING': 1,
    'ERROR': 0
}

def set_log_level(level_name: str):
    """Define o nível de log global para a execução atual."""
    _log_config.level = level_name.upper()

def log(message: str, level: str = 'INFO', force_print: bool = False):
    """
    Função centralizada para logs.
    Apenas mensagens com nível <= ao nível configurado serão exibidas.
    """
    level = level.upper()
    current_level_num = LOG_LEVELS.get(_log_config.level, 2)
    message_level_num = LOG_LEVELS.get(level, 2)
    
    if message_level_num <= current_level_num or force_print:
        prefix = f"[{level}] " if level != 'INFO' else ""
        print(f"{prefix}{message}")