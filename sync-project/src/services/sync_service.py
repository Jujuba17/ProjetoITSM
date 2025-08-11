# src/services/sync_service.py
"""
O serviço principal que contém a lógica de negócio para a sincronização.
Ele utiliza os outros serviços (Jira, Freshdesk) para realizar as tarefas.
"""
from datetime import datetime, timezone, timedelta

from . import jira_service, freshdesk_service
from ..utils import date_utils, text_utils
from ..utils.logger import log
from .jira_service import JIRA_PRIORITY_TO_FRESHDESK

# --- MELHORIA PRINCIPAL: Mapeamento com Fallbacks ---
# Agora, cada ID de status do Freshdesk mapeia para uma LISTA de nomes de transição.
# O script tentará os nomes na ordem em que aparecem na lista.
# IDs padrão Freshdesk: 2=Open, 3=Pending, 4=Resolved, 5=Closed, 6=Waiting on Customer, 7=Waiting on Third Party
DEFAULT_FRESHDESK_TO_JIRA_TRANSITION_MAP = {
    # Para "Open" (2), tentará 'Backlog', depois 'To Do', etc.
    2: ['Backlog', 'To Do', 'Tarefas Pendentes', 'A Fazer' , 'Lista de Pendências'],
    # Para "Pending" (3)
    3: ['In Progress', 'Em andamento', 'Em Análise'],
    # Para "Resolved" (4)
    4: ['Done', 'Concluído', 'Resolvido', 'Feito', 'Itens Concluídos'],
    # Para "Closed" (5), geralmente as mesmas transições de "Resolved"
    5: ['Done', 'Concluído', 'Resolvido', 'Feito', 'Closed', 'Fechado', 'Itens Concluídos'],
    # Para "Waiting on Customer" (6)
    6: ['Waiting for Customer', 'Esperando Cliente', 'Waiting on Customer', 'Aguardando Informações'],
    # Para "Waiting on Third Party" (7)
    7: ['Waiting for Vendor', 'Esperando Fornecedor', 'Blocked', 'Bloqueado']
}


def _get_jira_attachments(config, jira_ticket, adf_content, context_log=""):
    """
    Busca todos os anexos de um ticket do Jira:
      - os que estão no campo 'attachment' (seção de anexos geral do ticket)
      - os que estão no ADF (inseridos no corpo do texto)
    """
    if not config.get('SYNC_ATTACHMENTS', False):
        log(f"Sincronização de anexos está DESATIVADA para {context_log}. Pulando.", level='DEBUG')
        return []

    # Parte 1: Anexos da seção geral do ticket (campo 'attachment')
    general_attachment_ids = jira_service.get_ticket_general_attachments(jira_ticket)
    log(f"Encontrados {len(general_attachment_ids)} anexo(s) na seção geral de anexos do ticket para {context_log}.", level='DEBUG')

    # Parte 2: Anexos inseridos no corpo (extraídos do ADF)
    adf_attachment_refs = []
    if adf_content:
        adf_attachment_refs = jira_service.extract_attachment_refs_from_adf(adf_content)
        log(f"Encontrados {len(adf_attachment_refs)} anexo(s) no corpo do ADF para {context_log}.", level='DEBUG')
    else:
        log(f"Sem conteúdo ADF para extrair anexos do corpo em {context_log}.", level='DEBUG')

    # Parte 3: Combina as duas listas, removendo duplicatas (por ID)
    # Usamos um dicionário para garantir IDs únicos
    all_attachment_ids = {att_id for att_id in general_attachment_ids}
    for ref in adf_attachment_refs:
        all_attachment_ids.add(ref['id'])

    if not all_attachment_ids:
        log(f"NENHUM anexo encontrado em todo o ticket para {context_log}.", level='DEBUG')
        return []

    log(f"SUCESSO: {len(all_attachment_ids)} anexo(s) único(s) encontrados no ticket Jira {context_log}. Processando...", 'INFO')
    
    downloaded_attachments = []
    for i, attachment_id in enumerate(list(all_attachment_ids)):
        log(f"Processando anexo {i+1}/{len(all_attachment_ids)} com ID: {attachment_id}", level='DEBUG')
        
        details = jira_service.get_attachment_details(config, attachment_id)
        if not details or 'content' not in details:
            log(f"FALHA: Não foi possível obter detalhes ou a URL de conteúdo para o anexo ID {attachment_id}.", 'WARNING')
            continue
        
        log(f"Detalhes obtidos para o anexo {attachment_id}. Nome: {details.get('filename')}", level='DEBUG')

        content = jira_service.download_attachment(config, details['content'])
        if not content:
            log(f"FALHA: Download do anexo ID {attachment_id} retornou vazio.", 'WARNING')
            continue

        log(f"SUCESSO: Anexo {attachment_id} baixado. Tamanho: {len(content)} bytes.", 'INFO')
        downloaded_attachments.append({
            'filename': details.get('filename', f"file_{attachment_id}"),
            'content': content
        })
    
    log(f"Finalizado o processo de anexos para {context_log}. Total de anexos baixados: {len(downloaded_attachments)}.", 'DEBUG')
    return downloaded_attachments

def _sync_jira_to_freshdesk_updates(jira_tickets, config):
    """
    Sincroniza atualizações de tickets do Jira para o Freshdesk, incluindo
    prioridade e, opcionalmente, comentários e anexos.
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

        # Sincronizar prioridade
        jira_priority_name = jira_ticket['fields'].get('priority', {}).get('name')
        if jira_priority_name:
            fd_priority = JIRA_PRIORITY_TO_FRESHDESK.get(jira_priority_name)

            if fd_priority is not None:
                freshdesk_service.update_ticket_fields(config, fd_id, {'priority': fd_priority})

        # Sincronizar comentários (e anexos)
        if config.get('SYNC_COMMENTS', True):
            last_synced_comment_id = int(mapping[jira_key].get('last_jira_comment_id', 0))
            new_max_comment_id = last_synced_comment_id
            all_comments = jira_ticket['fields'].get('comment', {}).get('comments', [])
            sorted_comments = sorted(all_comments, key=lambda c: int(c['id']))

            for comment in sorted_comments:
                comment_id = int(comment['id'])
                if comment_id > last_synced_comment_id:
                    try:
                        comment_body_adf = comment.get('body')
                        comment_body = text_utils.extract_text_from_adf(comment_body_adf)

                        if config['BOT_COMMENT_TAG'] in comment_body:
                            continue

                        log(f"Novo comentário encontrado no Jira {jira_key} (ID: {comment_id}). Sincronizando...")

                        # Extrair anexos do corpo do comentário (ADF), se habilitado
                        attachments = _get_jira_attachments(config, jira_ticket, comment_body_adf, f"no comentário {comment_id}")

                        note = f"{config['BOT_COMMENT_TAG']}\n**Comentário do Jira por {comment['author']['displayName']}:**\n\n{comment_body}"
                        
                        # Adiciona a nota com anexos (se houver)
                        freshdesk_service.add_note(config, fd_id, note, attachments=attachments)

                        if comment_id > new_max_comment_id:
                            new_max_comment_id = comment_id
                    except (KeyError, IndexError, TypeError) as e:
                        log(f"Não foi possível extrair conteúdo do comentário ID {comment_id} do Jira {jira_key}: {e}", 'WARNING')
            
            if new_max_comment_id > last_synced_comment_id:
                mapping[jira_key]['last_jira_comment_id'] = new_max_comment_id
                log(f"Último ID de comentário do Jira para {jira_key} atualizado para {new_max_comment_id}", 'DEBUG')
        else:
            log(f"Sincronização de comentários Jira->Freshdesk pulada para {jira_key} (config 'SYNC_COMMENTS' é false).", 'DEBUG')

        mapping[jira_key]['last_jira_update'] = datetime.now(timezone.utc).isoformat()


def _sync_freshdesk_to_jira_updates(freshdesk_tickets, config):
    """
    Sincroniza atualizações do Freshdesk para o Jira, incluindo status e comentários.
    Tenta uma lista de nomes de transição para maior flexibilidade.
    """
    mapping = config['mapping_data']
    fd_id_to_jira_key = {str(v['freshdesk_id']): k for k, v in mapping.items()}
    log("\n--- Sincronizando Freshdesk -> Jira (Atualizações) ---")
    
    # Carrega o mapa da config do cliente; se não existir, usa nosso mapa padrão com fallbacks.
    transition_map = config.get('FRESHDESK_TO_JIRA_TRANSITION_MAP', DEFAULT_FRESHDESK_TO_JIRA_TRANSITION_MAP)
    log(f"Usando o seguinte mapa de transição Freshdesk->Jira: {transition_map}", 'DEBUG')

    for fd_ticket in freshdesk_tickets:
        fd_id_str = str(fd_ticket['id'])
        if fd_id_str not in fd_id_to_jira_key: continue

        jira_key = fd_id_to_jira_key[fd_id_str]
        last_sync = date_utils.parse_datetime(mapping[jira_key].get('last_freshdesk_update'))
        if last_sync and date_utils.parse_datetime(fd_ticket['updated_at']) <= last_sync: continue

        log(f"Verificando Freshdesk {fd_id_str} -> Jira {jira_key}")

        fd_status_id = fd_ticket.get('status')
        # Pega a lista de transições candidatas para este status
        candidate_transitions = transition_map.get(fd_status_id)

        if not candidate_transitions:
            log(f"Status do Freshdesk ID {fd_status_id} não possui mapeamento de transição no Jira. Pulando mudança de status.", 'WARNING')
        else:
            # Garante que temos uma lista, mesmo que o cliente configure uma string por engano
            if isinstance(candidate_transitions, str):
                candidate_transitions = [candidate_transitions]

            transition_applied = False
            for transition_name in candidate_transitions:
                log(f"Tentando transição '{transition_name}' para o Jira {jira_key}...", 'DEBUG')
                if jira_service.transition_issue(config, jira_key, transition_name):
                    log(f"SUCESSO: Transição '{transition_name}' aplicada com sucesso para o Jira {jira_key}.", 'INFO')
                    transition_applied = True
                    break  # Para o loop assim que uma transição funcionar
                else:
                    log(f"Transição '{transition_name}' falhou ou não existe. Tentando próximo candidato...", 'DEBUG')
            
            if not transition_applied:
                log(f"AVISO: Nenhuma das transições candidatas {candidate_transitions} funcionou para o Jira {jira_key}.", 'WARNING')

        # Sincronização de comentários
        if config.get('SYNC_COMMENTS', True):
            for conv in freshdesk_service.fetch_conversations(config, fd_id_str):
                if not last_sync or date_utils.parse_datetime(conv['updated_at']) > last_sync:
                    if config['BOT_COMMENT_TAG'] not in conv.get('body_text', ''):
                        note_type = "Nota Privada" if conv.get('private', True) else "Resposta Pública"
                        user_name = conv.get('user', {}).get('name', 'Usuário')
                        comment = f"{config['BOT_COMMENT_TAG']}\n**{note_type} do Freshdesk por {user_name}:**\n\n{conv['body_text']}"
                        jira_service.add_comment(config, jira_key, comment)
        else:
            log(f"Sincronização de conversas Freshdesk->Jira pulada para {fd_id_str} (config 'SYNC_COMMENTS' é false).", 'DEBUG')

        mapping[jira_key]['last_freshdesk_update'] = datetime.now(timezone.utc).isoformat()

def _record_match(mapping, config, jira_ticket, fd_ticket, match_type):
    """Registra um mapeamento encontrado e adiciona um comentário no Jira."""
    jira_key = jira_ticket['key']
    fd_id = fd_ticket['id']
    sync_time = datetime.now(timezone.utc).isoformat()
    
    log(f"MAPEAMENTO ENCONTRADO por {match_type}: Jira {jira_key} -> Freshdesk {fd_id}", 'INFO')
    
    mapping[jira_key] = {
        'freshdesk_id': int(fd_id),
        'last_jira_update': sync_time,
        'last_freshdesk_update': sync_time,
        'last_jira_comment_id': 0 # Inicia o contador de comentários
    }
    comment = f"{config['BOT_COMMENT_TAG']} Ticket mapeado para o Freshdesk ID existente: {fd_id} (correspondência por {match_type})."
    jira_service.add_comment(config, jira_key, comment)
    return jira_key, str(fd_id)

def _create_new_ticket(mapping, config, jira_ticket):
    """Cria um novo ticket no Freshdesk para um Jira não mapeado, incluindo anexos."""
    log(f"Nenhum match encontrado para {jira_ticket['key']}. Criando novo ticket no Freshdesk...", 'INFO')
    description = jira_service.extract_description(jira_ticket) or "Descrição não fornecida."

    # Extrair anexos da descrição e do campo de anexo geral
    description_adf = jira_ticket['fields'].get('description')
    attachments = _get_jira_attachments(config, jira_ticket, description_adf, f"na descrição do ticket {jira_ticket['key']}")

    new_fd_ticket = freshdesk_service.create_ticket(config, jira_ticket, description, attachments=attachments)
    
    if new_fd_ticket and 'id' in new_fd_ticket:
        fd_id = new_fd_ticket['id']
        sync_time = datetime.now(timezone.utc).isoformat()
        mapping[jira_ticket['key']] = {
            'freshdesk_id': fd_id,
            'last_jira_update': sync_time,
            'last_freshdesk_update': sync_time,
            'last_jira_comment_id': 0 # Inicia o contador de comentários
        }
        comment = f"{config['BOT_COMMENT_TAG']} Ticket criado e sincronizado com o Freshdesk. ID: {fd_id}"
        jira_service.add_comment(config, jira_ticket['key'], comment)
        log(f"Ticket {jira_ticket['key']} mapeado com sucesso para Freshdesk ID {fd_id}.")
    else:
        log(f"Falha ao criar ticket no Freshdesk para {jira_ticket['key']}.", 'ERROR')

def _find_and_map_new_tickets(jira_tickets, config):
    """Lida com tickets do Jira não mapeados."""
    mapping = config['mapping_data']
    unmapped_jira = [t for t in jira_tickets if t['key'] not in mapping]
    if not unmapped_jira:
        log("\nNenhum ticket novo do Jira para mapear.", 'INFO')
        return
        
    log(f"\n--- Iniciando mapeamento para {len(unmapped_jira)} novos tickets do Jira ---")

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
    
    else:
        log("Mapeamento inteligente DESATIVADO. Usando data de corte...", 'INFO')
        first_run_timestamp_str = config.get('FIRST_RUN_TIMESTAMP')
        if not first_run_timestamp_str:
            first_run_timestamp_str = datetime.now(timezone.utc).isoformat()
            config['FIRST_RUN_TIMESTAMP'] = first_run_timestamp_str
            log(f"Primeira execução com mapeamento desativado. Data de corte registrada: {first_run_timestamp_str}", 'WARNING')
        first_run_date = date_utils.parse_datetime(first_run_timestamp_str)
        for jira_ticket in unmapped_jira:
            ticket_creation_date = date_utils.parse_datetime(jira_ticket['fields']['created'])
            if ticket_creation_date and first_run_date and ticket_creation_date >= first_run_date:
                log(f"Ticket {jira_ticket['key']} é novo (pós data de corte). Criando no Freshdesk...")
                _create_new_ticket(mapping, config, jira_ticket)
            else:
                log(f"Ignorando ticket antigo {jira_ticket['key']} (criado antes da data de corte).")

def run_sync_for_client(config):
    """
    Função que executa a sequência completa de sincronização e retorna
    as contagens de tickets processados.
    """
    sync_days = config.get("SYNC_DAYS_AGO", 1)
    since_date_str = (datetime.now(timezone.utc) - timedelta(days=sync_days)).strftime('%Y-%m-%d')
    
    created_since_filter = None
    if not config.get('ENABLE_SMART_MAPPING', False):
        first_run_timestamp_str = config.get('FIRST_RUN_TIMESTAMP')
        if first_run_timestamp_str:
            created_since_filter = date_utils.parse_datetime(first_run_timestamp_str).strftime('%Y-%m-%d')
            log(f"Mapeamento inteligente desativado. Apenas tickets criados a partir de {created_since_filter} serão considerados para mapeamento.")
    
    jira_tickets = jira_service.fetch_updated_tickets(config, since_date_str, created_since_filter)
    freshdesk_tickets = freshdesk_service.fetch_updated_tickets(config, since_date_str)
    log(f"Encontrados {len(jira_tickets)} tickets no Jira e {len(freshdesk_tickets)} no Freshdesk para processar.", 'INFO')

    if not jira_tickets and not freshdesk_tickets:
        log("Nenhum ticket para sincronizar.", 'INFO')
        return 0, 0

    _sync_jira_to_freshdesk_updates(jira_tickets, config)
    _sync_freshdesk_to_jira_updates(freshdesk_tickets, config)
    _find_and_map_new_tickets(jira_tickets, config)

    return len(jira_tickets), len(freshdesk_tickets)