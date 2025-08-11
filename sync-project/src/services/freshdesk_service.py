# src/services/freshdesk_service.py
"""
Serviço responsável por todas as interações com a API do Freshdesk.
"""
from ..utils.api_client import api_request
from ..utils.logger import log
from .jira_service import JIRA_PRIORITY_TO_FRESHDESK, JIRA_STATUS_TO_FRESHDESK

def fetch_updated_tickets(config, since_date_str):
    """
    Busca tickets do Freshdesk atualizados desde uma data específica,
    opcionalmente filtrados por empresa.
    """
    # --- ALTERAÇÃO: Ler o company_id da configuração ---
    company_id = config.get('FRESHDESK_COMPANY_ID')
    log_msg = f"Buscando tickets do Freshdesk atualizados desde {since_date_str}"
    if company_id:
        log_msg += f" para a Empresa ID: {company_id}..."
    else:
        log_msg += " (sem filtro de empresa)..."
    log(log_msg)
    
    updated_since = f"{since_date_str}T00:00:00Z"
    url = f"https://{config['FRESHDESK_DOMAIN']}.freshdesk.com/api/v2/tickets"
    params = {'updated_since': updated_since, 'include': 'description', 'order_by': 'updated_at', 'order_type': 'desc'}

    # --- ALTERAÇÃO: Adicionar o filtro de empresa se ele existir ---
    if company_id:
        params['company_id'] = company_id
    
    return api_request('GET', url, config['FRESHDESK_AUTH'], params=params) or []

def create_ticket(config, jira_ticket, description_text):
    """Cria um novo ticket no Freshdesk, associando-o a uma empresa se configurado."""
    log(f"Criando ticket no Freshdesk para o Jira {jira_ticket['key']}...")
    url = f"https://{config['FRESHDESK_DOMAIN']}.freshdesk.com/api/v2/tickets"
    
    jira_priority_name = jira_ticket['fields'].get('priority', {}).get('name')
    fd_priority = config['JIRA_TO_FRESHDESK_PRIORITY'].get(jira_priority_name, 1) # Default 'Low'
    fd_status = config['JIRA_TO_FRESHDESK_STATUS'].get(jira_ticket['fields']['status']['name'], 2) # Default 'Open'

    payload = {
        'subject': jira_ticket['fields']['summary'],
        'description': description_text,
        'email': config['JIRA_USER_EMAIL'],
        'priority': fd_priority,
        'status': fd_status,
        'tags': [jira_ticket['key']]
    }

    # --- ALTERAÇÃO: Adicionar o company_id ao criar o ticket ---
    company_id = config.get('FRESHDESK_COMPANY_ID')
    if company_id:
        payload['company_id'] = int(company_id) # API espera um inteiro
        log(f"Ticket será associado à Empresa ID: {company_id}", 'DEBUG')

    return api_request('POST', url, config['FRESHDESK_AUTH'], json_data=payload)

def fetch_all_relevant_tickets(config, since_date_str):
    """
    Busca todos os tickets recentes do Freshdesk para o mapeamento inteligente,
    filtrados por empresa se configurado.
    """
    # --- ALTERAÇÃO: Ler o company_id da configuração ---
    company_id = config.get('FRESHDESK_COMPANY_ID')
    log_msg = f"Buscando todos os tickets do Freshdesk desde {since_date_str} para mapeamento"
    if company_id:
        log_msg += f" para a Empresa ID: {company_id}..."
    else:
        log_msg += "..."
    log(log_msg)

    url = f"https://{config['FRESHDESK_DOMAIN']}.freshdesk.com/api/v2/tickets"
    params = {'updated_since': f"{since_date_str}T00:00:00Z", 'include': 'description', 'per_page': 100}

    # --- ALTERAÇÃO: Adicionar o filtro de empresa se ele existir ---
    if company_id:
        params['company_id'] = company_id
        
    return api_request('GET', url, config['FRESHDESK_AUTH'], params=params) or []

# --- Funções fetch_conversations, add_note, update_ticket_fields não precisam de alteração ---
def fetch_conversations(config, ticket_id):
    """Busca todas as conversas de um ticket."""
    log(f"Buscando conversas do Freshdesk para o ticket ID: {ticket_id}...")
    url = f"https://{config['FRESHDESK_DOMAIN']}.freshdesk.com/api/v2/tickets/{ticket_id}/conversations"
    return api_request('GET', url, config['FRESHDESK_AUTH']) or []

def add_note(config, ticket_id, note_text):
    """Adiciona uma nota privada a um ticket."""
    log(f"Adicionando nota privada ao Freshdesk {ticket_id}...")
    url = f"https://{config['FRESHDESK_DOMAIN']}.freshdesk.com/api/v2/tickets/{ticket_id}/notes"
    payload = {'body': note_text, 'private': True}
    api_request('POST', url, config['FRESHDESK_AUTH'], json_data=payload)

def update_ticket_fields(config, ticket_id, update_fields):
    """Atualiza campos específicos de um ticket."""
    log(f"Atualizando campos do ticket Freshdesk {ticket_id}: {update_fields}")
    url = f"https://{config['FRESHDESK_DOMAIN']}.freshdesk.com/api/v2/tickets/{ticket_id}"
    return api_request('PUT', url, config['FRESHDESK_AUTH'], json_data=update_fields)

#função para buscar anexos de um ticket
def create_ticket(config, jira_ticket, description_text, attachments=None):
    """
    Cria um novo ticket no Freshdesk.
    [CORRIGIDO] Lida corretamente com os nomes dos campos de tags para
    requisições JSON e multipart.
    """
    log(f"Criando ticket no Freshdesk para o Jira {jira_ticket['key']}...")
    url = f"https://{config['FRESHDESK_DOMAIN']}.freshdesk.com/api/v2/tickets"
    
    # jira_priority_name = jira_ticket['fields'].get('priority', {}).get('name')
    # fd_priority = config['JIRA_TO_FRESHDESK_PRIORITY'].get(jira_priority_name, 1) # Default 'Low'
    # fd_status = config['JIRA_TO_FRESHDESK_STATUS'].get(jira_ticket['fields']['status']['name'], 2) # Default 'Open'
    jira_priority_name = jira_ticket['fields'].get('priority', {}).get('name')
    fd_priority = JIRA_PRIORITY_TO_FRESHDESK.get(jira_priority_name, 1)  # Padrão 'Low' (ID 1)

    jira_status_name = jira_ticket['fields']['status']['name']
    fd_status = JIRA_STATUS_TO_FRESHDESK.get(jira_status_name, 2)  # Padrão 'Open' (ID 2)

    files = []
    if attachments:
        log(f"Anexando {len(attachments)} arquivo(s) na criação do ticket.", 'DEBUG')
        for att in attachments:
            files.append(('attachments[]', (att['filename'], att['content'])))

    # Construir o payload base
    base_data = {
        'subject': jira_ticket['fields']['summary'],
        'description': description_text,
        'email': config['JIRA_USER_EMAIL'],
        'priority': fd_priority,
        'status': fd_status,
    }
    company_id = config.get('FRESHDESK_COMPANY_ID')
    if company_id:
        base_data['company_id'] = int(company_id)

    # A distinção crítica acontece aqui:
    if files:
        # Modo Multipart: usar 'data' e 'files', e a tag é 'tags[]'
        multipart_data = base_data.copy()
        multipart_data['tags[]'] = jira_ticket['key'] # API multipart espera 'tags[]'
        return api_request('POST', url, config['FRESHDESK_AUTH'], data=multipart_data, files=files)
    else:
        # Modo JSON: usar 'json_data', e a tag é 'tags' como uma lista
        json_payload = base_data.copy()
        json_payload['tags'] = [jira_ticket['key']] # API JSON espera 'tags'
        return api_request('POST', url, config['FRESHDESK_AUTH'], json_data=json_payload)
    
def add_note(config, ticket_id, note_text, attachments=None):
    """
    Adiciona uma nota privada a um ticket.
    Aceita anexos para envio multipart.
    """
    log(f"Adicionando nota privada ao Freshdesk {ticket_id}...")
    url = f"https://{config['FRESHDESK_DOMAIN']}.freshdesk.com/api/v2/tickets/{ticket_id}/notes"
    
    data = {'body': note_text, 'private': True}
    
    files = []
    if attachments:
        log(f"Anexando {len(attachments)} arquivo(s) na nota.", 'DEBUG')
        for att in attachments:
            files.append(('attachments[]', (att['filename'], att['content'])))

    if files:
        return api_request('POST', url, config['FRESHDESK_AUTH'], data=data, files=files)
    else:
        return api_request('POST', url, config['FRESHDESK_AUTH'], json_data=data)