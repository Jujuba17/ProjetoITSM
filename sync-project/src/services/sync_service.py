# src/services/sync_service.py
"""
O serviço principal que contém a lógica de negócio para a sincronização.
Ele utiliza os outros serviços (Jira, Freshdesk) para realizar as tarefas.
"""
from datetime import datetime, timezone, timedelta

from . import jira_service, freshdesk_service
from ..utils import date_utils, text_utils
from ..utils.logger import log

# --- Funções _sync_jira_to_freshdesk_updates e _sync_freshdesk_to_jira_updates (inalteradas) ---

def _sync_jira_to_freshdesk_updates(jira_tickets, config):
    """
    Sincroniza atualizações de tickets do Jira para o Freshdesk, incluindo
    prioridade e comentários.
    """
    mapping = config['mapping_data']
    log("\n--- Sincronizando Jira -> Freshdesk (Atualizações) ---")
    
    for jira_ticket in jira_tickets:
        jira_key = jira_ticket['key']
        if jira_key not in mapping: continue

        last_sync_time = date_utils.parse_datetime(mapping[jira_key].get('last_jira_update'))
        if last_sync_time and date_utils.parse_datetime(jira_ticket['fields']['updated']) <= last_sync_time:
            continue

        fd_id = mapping[jira_key]['freshdesk_id']
        log(f"Verificando Jira {jira_key} -> Freshdesk {fd_id}")

        jira_priority_name = jira_ticket['fields'].get('priority', {}).get('name')
        if jira_priority_name:
            fd_priority = config.get('JIRA_TO_FRESHDESK_PRIORITY', {}).get(jira_priority_name)
            if fd_priority is not None:
                freshdesk_service.update_ticket_fields(config, fd_id, {'priority': fd_priority})

        last_synced_comment_id = int(mapping[jira_key].get('last_jira_comment_id', 0))
        new_max_comment_id = last_synced_comment_id
        all_comments = jira_ticket['fields'].get('comment', {}).get('comments', [])
        sorted_comments = sorted(all_comments, key=lambda c: int(c['id']))

        for comment in sorted_comments:
            comment_id = int(comment['id'])
            if comment_id > last_synced_comment_id:
                try:
                    comment_body = comment['body']['content'][0]['content'][0]['text']
                    if config['BOT_COMMENT_TAG'] not in comment_body:
                        log(f"Novo comentário encontrado no Jira {jira_key} (ID: {comment_id}). Sincronizando...")
                        note = f"{config['BOT_COMMENT_TAG']}\n**Comentário do Jira por {comment['author']['displayName']}:**\n\n{comment_body}"
                        freshdesk_service.add_note(config, fd_id, note)
                        if comment_id > new_max_comment_id:
                            new_max_comment_id = comment_id
                except (KeyError, IndexError):
                    log(f"Não foi possível extrair conteúdo do comentário ID {comment_id} do Jira {jira_key}", 'WARNING')
        
        if new_max_comment_id > last_synced_comment_id:
            mapping[jira_key]['last_jira_comment_id'] = new_max_comment_id
            log(f"Último ID de comentário do Jira para {jira_key} atualizado para {new_max_comment_id}", 'DEBUG')

        mapping[jira_key]['last_jira_update'] = datetime.now(timezone.utc).isoformat()


def _sync_freshdesk_to_jira_updates(freshdesk_tickets, config):
    mapping = config['mapping_data']
    fd_id_to_jira_key = {str(v['freshdesk_id']): k for k, v in mapping.items()}
    log("\n--- Sincronizando Freshdesk -> Jira (Atualizações) ---")
    
    for fd_ticket in freshdesk_tickets:
        fd_id_str = str(fd_ticket['id'])
        if fd_id_str not in fd_id_to_jira_key: continue

        jira_key = fd_id_to_jira_key[fd_id_str]
        last_sync = date_utils.parse_datetime(mapping[jira_key].get('last_freshdesk_update'))
        if last_sync and date_utils.parse_datetime(fd_ticket['updated_at']) <= last_sync: continue

        log(f"Verificando Freshdesk {fd_id_str} -> Jira {jira_key}")

        transition_name = config['FRESHDESK_TO_JIRA_TRANSITION_NAME'].get(fd_ticket['status'])
        if transition_name:
            jira_service.transition_issue(config, jira_key, transition_name)

        for conv in freshdesk_service.fetch_conversations(config, fd_id_str):
            if not last_sync or date_utils.parse_datetime(conv['updated_at']) > last_sync:
                if config['BOT_COMMENT_TAG'] not in conv.get('body_text', ''):
                    note_type = "Nota Privada" if conv.get('private', True) else "Resposta Pública"
                    user_name = conv.get('user', {}).get('name', 'Usuário')
                    comment = f"{config['BOT_COMMENT_TAG']}\n**{note_type} do Freshdesk por {user_name}:**\n\n{conv['body_text']}"
                    jira_service.add_comment(config, jira_key, comment)

        mapping[jira_key]['last_freshdesk_update'] = datetime.now(timezone.utc).isoformat()

# --- FIM DAS FUNÇÕES INALTERADAS ---

def _record_match(mapping, config, jira_ticket, fd_ticket, match_type):
    """Registra um mapeamento encontrado e adiciona um comentário no Jira."""
    jira_key = jira_ticket['key']
    fd_id = fd_ticket['id']
    sync_time = datetime.now(timezone.utc).isoformat()
    
    log(f"MAPEAMENTO ENCONTRADO por {match_type}: Jira {jira_key} -> Freshdesk {fd_id}", 'INFO')
    
    mapping[jira_key] = {
        'freshdesk_id': int(fd_id),
        'last_jira_update': sync_time,
        'last_freshdesk_update': sync_time
    }
    comment = f"{config['BOT_COMMENT_TAG']} Ticket mapeado para o Freshdesk ID existente: {fd_id} (correspondência por {match_type})."
    jira_service.add_comment(config, jira_key, comment)
    return jira_key, str(fd_id)

def _create_new_ticket(mapping, config, jira_ticket):
    """Cria um novo ticket no Freshdesk para um Jira não mapeado."""
    log(f"Nenhum match encontrado para {jira_ticket['key']}. Criando novo ticket no Freshdesk...", 'INFO')
    description = jira_service.extract_description(jira_ticket) or "Descrição não fornecida."
    new_fd_ticket = freshdesk_service.create_ticket(config, jira_ticket, description)
    
    if new_fd_ticket and 'id' in new_fd_ticket:
        fd_id = new_fd_ticket['id']
        sync_time = datetime.now(timezone.utc).isoformat()
        mapping[jira_ticket['key']] = {
            'freshdesk_id': fd_id,
            'last_jira_update': sync_time,
            'last_freshdesk_update': sync_time
        }
        comment = f"{config['BOT_COMMENT_TAG']} Ticket criado e sincronizado com o Freshdesk. ID: {fd_id}"
        jira_service.add_comment(config, jira_ticket['key'], comment)
        log(f"Ticket {jira_ticket['key']} mapeado com sucesso para Freshdesk ID {fd_id}.")
    else:
        log(f"Falha ao criar ticket no Freshdesk para {jira_ticket['key']}.", 'ERROR')


def _find_and_map_new_tickets(jira_tickets, config):
    """
    [CORRIGIDO] Lida com tickets do Jira não mapeados.
    - Se ENABLE_SMART_MAPPING é true, tenta um mapeamento inteligente.
    - Se é false, usa a lógica de data de corte (FIRST_RUN_TIMESTAMP).
    """
    mapping = config['mapping_data']
    unmapped_jira = [t for t in jira_tickets if t['key'] not in mapping]
    if not unmapped_jira:
        log("\nNenhum ticket novo do Jira para mapear.", 'INFO')
        return

    log(f"\n--- Iniciando mapeamento para {len(unmapped_jira)} novos tickets do Jira ---")

    # --- Cenário 1: Mapeamento Inteligente ATIVADO ---
    if config.get('ENABLE_SMART_MAPPING', True):
        log("Mapeamento inteligente ATIVADO. Buscando correspondências...", 'INFO')
        lookback_days = config.get("MAPPING_LOOKBACK_DAYS", 30)
        since_date = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime('%Y-%m-%d')
        fd_candidates = freshdesk_service.fetch_all_relevant_tickets(config, since_date)

        if not fd_candidates:
            log("Nenhum ticket recente encontrado no Freshdesk para mapear. Criando todos...", 'INFO')
            for jira_ticket in unmapped_jira:
                _create_new_ticket(mapping, config, jira_ticket)
            return

        mapped_fd_ids = {str(v['freshdesk_id']) for v in mapping.values()}
        fd_title_map, fd_desc_map = {}, {}

        for ticket in fd_candidates:
            if str(ticket['id']) in mapped_fd_ids: continue
            
            norm_title = text_utils.normalize_text(ticket['subject'])
            if norm_title: fd_title_map.setdefault(norm_title, []).append(ticket)
            
            desc_html = ticket.get('description_text', ticket.get('description', ''))
            if desc_html:
                norm_desc = text_utils.normalize_text(text_utils.strip_html_tags(desc_html))
                if len(norm_desc) > 20: fd_desc_map.setdefault(norm_desc, []).append(ticket)
        
        jira_matched_keys, fd_matched_ids = set(), set()

        for jira_ticket in unmapped_jira:
            norm_title = text_utils.normalize_text(jira_ticket['fields']['summary'])
            if norm_title in fd_title_map:
                for fd_ticket in fd_title_map[norm_title]:
                    if str(fd_ticket['id']) not in fd_matched_ids:
                        key, fd_id = _record_match(mapping, config, jira_ticket, fd_ticket, "título")
                        jira_matched_keys.add(key)
                        fd_matched_ids.add(fd_id)
                        break
        
        for jira_ticket in unmapped_jira:
            if jira_ticket['key'] in jira_matched_keys: continue
            desc_text = jira_service.extract_description(jira_ticket)
            if desc_text:
                norm_desc = text_utils.normalize_text(desc_text)
                if len(norm_desc) > 20 and norm_desc in fd_desc_map:
                    for fd_ticket in fd_desc_map[norm_desc]:
                        if str(fd_ticket['id']) not in fd_matched_ids:
                            key, fd_id = _record_match(mapping, config, jira_ticket, fd_ticket, "descrição")
                            jira_matched_keys.add(key)
                            fd_matched_ids.add(fd_id)
                            break
        
        log("\n--- Criando tickets para os Jira que não foram mapeados ---", 'INFO')
        for jira_ticket in unmapped_jira:
            if jira_ticket['key'] not in jira_matched_keys:
                _create_new_ticket(mapping, config, jira_ticket)
    
    # --- Cenário 2: Mapeamento Inteligente DESATIVADO ---
    else:
        log("Mapeamento inteligente DESATIVADO. Usando data de corte...", 'INFO')
        
        first_run_timestamp_str = config.get('FIRST_RUN_TIMESTAMP')
        if not first_run_timestamp_str:
            # Define a data de corte agora. O orquestrador será responsável por salvar.
            first_run_timestamp_str = datetime.now(timezone.utc).isoformat()
            config['FIRST_RUN_TIMESTAMP'] = first_run_timestamp_str
            log(f"Primeira execução com mapeamento desativado. Data de corte registrada: {first_run_timestamp_str}", 'WARNING')

        first_run_date = date_utils.parse_datetime(first_run_timestamp_str)
        
        for jira_ticket in unmapped_jira:
            ticket_creation_date = date_utils.parse_datetime(jira_ticket['fields']['created'])
            
            # Só cria o ticket se ele foi criado DEPOIS da data de corte.
            if ticket_creation_date and first_run_date and ticket_creation_date >= first_run_date:
                log(f"Ticket {jira_ticket['key']} é novo (pós data de corte). Criando no Freshdesk...")
                _create_new_ticket(mapping, config, jira_ticket)
            else:
                log(f"Ignorando ticket antigo {jira_ticket['key']} (criado antes da data de corte).")
       

def run_sync_for_client(config):
    """
    [CORRIGIDO] Função que executa a sequência completa de sincronização.
    A condição para aplicar o filtro de data de corte foi corrigida.
    """
    sync_days = config.get("SYNC_DAYS_AGO", 1)
    since_date_str = (datetime.now(timezone.utc) - timedelta(days=sync_days)).strftime('%Y-%m-%d')
    
    # Prepara o filtro de data de criação se o smart mapping estiver desativado
    created_since_filter = None
    # [CORREÇÃO APLICADA] Usar False como padrão para a condição funcionar corretamente
    # quando a flag é explicitamente 'false' ou não está presente.
    if not config.get('ENABLE_SMART_MAPPING', False):
        first_run_timestamp_str = config.get('FIRST_RUN_TIMESTAMP')
        if first_run_timestamp_str:
            # Formata para 'YYYY-MM-DD' para a query JQL
            created_since_filter = date_utils.parse_datetime(first_run_timestamp_str).strftime('%Y-%m-%d')
            log(f"Mapeamento inteligente desativado. Apenas tickets criados a partir de {created_since_filter} serão considerados para mapeamento.")
    
    # Etapa 1: Buscar dados
    jira_tickets = jira_service.fetch_updated_tickets(config, since_date_str, created_since_filter)
    freshdesk_tickets = freshdesk_service.fetch_updated_tickets(config, since_date_str)
    log(f"Encontrados {len(jira_tickets)} tickets no Jira e {len(freshdesk_tickets)} no Freshdesk para processar.", 'INFO')

    if not jira_tickets and not freshdesk_tickets:
        log("Nenhum ticket para sincronizar.", 'INFO')
        return

    _sync_jira_to_freshdesk_updates(jira_tickets, config)
    _sync_freshdesk_to_jira_updates(freshdesk_tickets, config)
    _find_and_map_new_tickets(jira_tickets, config)