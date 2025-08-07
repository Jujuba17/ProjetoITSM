# src/orchestrator.py
"""
Orquestrador principal do processo de sincronização.
"""
import os
import json
from datetime import datetime, timezone
from requests.auth import HTTPBasicAuth

from .services import sync_service
from .utils.logger import log, set_log_level
from .utils import date_utils # Importar para usar a função de parse

def _load_client_config(client_folder_path):
    # ... (código inalterado) ...
    config_path = os.path.join(client_folder_path, 'config.json')
    if not os.path.exists(config_path):
        log(f"Arquivo 'config.json' não encontrado em {client_folder_path}", 'ERROR')
        return None

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except Exception as e:
        log(f"Erro ao carregar ou decodificar config.json: {e}", 'ERROR')
        return None
    
    required_keys = ['JIRA_URL', 'JIRA_USER_EMAIL', 'JIRA_API_TOKEN', 'JIRA_PROJECT_KEY', 'FRESHDESK_DOMAIN', 'FRESHDESK_API_KEY']
    if not all(key in config for key in required_keys):
        log("Config.json está faltando uma ou mais chaves obrigatórias.", 'ERROR')
        return None

    return config

def _prepare_client_environment(config, client_folder_path):
    """Prepara o dicionário de configuração com todos os dados e padrões."""
    set_log_level(config.get('LOG_LEVEL', 'INFO'))
    log(f"Nível de log definido para: {config.get('LOG_LEVEL', 'INFO')}")

    # Unificação de Flags: Garante retrocompatibilidade
    if 'ENABLE_SMART_MAPPING' not in config:
        config['ENABLE_SMART_MAPPING'] = config.get('ENABLE_SMART_INITIAL_MAPPING', True)

    mapping_path = os.path.join(client_folder_path, 'mapping.json')
    mapping_data = {}
    if os.path.exists(mapping_path):
        try:
            with open(mapping_path, 'r', encoding='utf-8') as f:
                mapping_data = json.load(f)
        except json.JSONDecodeError:
            log("Arquivo mapping.json corrompido. Começando com mapeamento vazio.", 'WARNING')
    
    config['JIRA_AUTH'] = HTTPBasicAuth(config['JIRA_USER_EMAIL'], config['JIRA_API_TOKEN'])
    config['FRESHDESK_AUTH'] = (config['FRESHDESK_API_KEY'], 'X')
    config['MAPPING_FILE_PATH'] = mapping_path
    config['mapping_data'] = mapping_data

    config.setdefault('JIRA_TO_FRESHDESK_PRIORITY', {"Highest": 4, "High": 3, "Medium": 2, "Low": 1, "Lowest": 1})
    config.setdefault('JIRA_TO_FRESHDESK_STATUS', {'Backlog': 2, 'Em andamento': 3, 'Concluído': 4, 'Closed': 4})
    config.setdefault('FRESHDESK_TO_JIRA_TRANSITION_NAME', {2: "Lista de pendências", 3: "Em andamento", 4: "Itens concluídos", 5: "Itens concluídos"})
    config.setdefault('BOT_COMMENT_TAG', "[SyncBot]")
    
    return config

def _save_mapping(config):

    if not config.get('mapping_data'):
        log("Nenhum dado de mapeamento para salvar.", 'INFO')
        return
    
    try:
        with open(config['MAPPING_FILE_PATH'], 'w', encoding='utf-8') as f:
            json.dump(config['mapping_data'], f, indent=4)
        log(f"Mapeamento salvo com sucesso. Total de tickets: {len(config['mapping_data'])}")
    except Exception as e:
        log(f"ERRO ao salvar arquivo de mapeamento: {e}", 'ERROR')

def _save_config_if_changed(config, client_folder_path):
    """
    [CORRIGIDO] Salva o config.json se a FIRST_RUN_TIMESTAMP foi adicionada,
    preservando a estrutura original do arquivo e evitando salvar chaves padrão.
    """
    config_path = os.path.join(client_folder_path, 'config.json')
    
    try:
        # Carrega a configuração original (como estava no disco) para comparar
        with open(config_path, 'r', encoding='utf-8') as f:
            original_config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        log(f"Não foi possível carregar o config.json original para comparação: {e}", 'ERROR')
        return

    # Verifica se a chave foi adicionada durante a execução (e não existia no arquivo original)
    if 'FIRST_RUN_TIMESTAMP' in config and 'FIRST_RUN_TIMESTAMP' not in original_config:
        log("Detectada nova 'FIRST_RUN_TIMESTAMP'. Salvando no config.json...", 'INFO')
        
        # Cria uma cópia da configuração original, adicionando APENAS o novo campo
        updated_config = original_config.copy()
        updated_config['FIRST_RUN_TIMESTAMP'] = config['FIRST_RUN_TIMESTAMP']
        
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(updated_config, f, indent=4)
            log("Config.json atualizado com sucesso apenas com a nova FIRST_RUN_TIMESTAMP.", 'INFO')
        except Exception as e:
            log(f"ERRO ao salvar config.json atualizado: {e}", 'ERROR')

def process_client(client_folder_path, client_name):
    """Processa um único cliente."""
    log(f"\n{'─'*25} Processando cliente: {client_name.upper()} {'─'*25}", force_print=True)
    
    config = _load_client_config(client_folder_path)
    if not config: return

    full_config = _prepare_client_environment(config, client_folder_path)
    
    try:
        sync_service.run_sync_for_client(full_config)
        
        # [CORREÇÃO 3] Salva o mapeamento e a configuração (se necessário)
        _save_mapping(full_config)
        _save_config_if_changed(full_config, client_folder_path)

        log(f"\nCliente {client_name.upper()} processado com sucesso.", force_print=True)
    except Exception as e:
        log(f"ERRO inesperado durante a sincronização de {client_name}: {e}", 'ERROR', force_print=True)
        import traceback
        traceback.print_exc()

def main():
    
    start_time = datetime.now()
    log("\n" + "="*70, force_print=True)
    log(f"INICIANDO SINCRONIZAÇÃO GERAL EM: {start_time.strftime('%Y-%m-%d %H:%M:%S')}", force_print=True)
    log("="*70, force_print=True)
    
    base_dir = os.getcwd()
    clients_root = os.path.join(base_dir, 'clients')
    
    if not os.path.isdir(clients_root):
        log(f"ERRO: Diretório 'clients' não encontrado em {base_dir}", 'ERROR', force_print=True)
        return

    client_dirs = [d for d in os.listdir(clients_root) if os.path.isdir(os.path.join(clients_root, d))]
    
    if not client_dirs:
        log("Nenhum diretório de cliente encontrado na pasta 'clients'.", 'WARNING', force_print=True)
        return
        
    log(f"Encontrados {len(client_dirs)} clientes para processar: {', '.join(client_dirs)}", force_print=True)
    
    for client_name in client_dirs:
        process_client(os.path.join(clients_root, client_name), client_name)
        
    end_time = datetime.now()
    log("\n" + "="*70, force_print=True)
    log(f"SINCRONIZAÇÃO GERAL CONCLUÍDA EM: {end_time.strftime('%Y-%m-%d %H:%M:%S')}", force_print=True)
    log(f"Tempo total de execução: {end_time - start_time}", force_print=True)
    log("="*70, force_print=True)