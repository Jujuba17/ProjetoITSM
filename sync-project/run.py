# run.py
"""
Ponto de entrada principal da aplicação de sincronização.
Este script inicia o processo chamando o orquestrador.
"""
from src.orchestrator import main
from src.utils.logger import log

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        log(f"ERRO FATAL NO SCRIPT PRINCIPAL: {e}", level='ERROR', force_print=True)
        import traceback
        traceback.print_exc()
        exit(1)