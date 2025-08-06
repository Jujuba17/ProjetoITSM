# src/services/freshdesk_service.py
"""
Serviço responsável por todas as interações com a API do Freshdesk.
"""
from ..utils.api_client import api_request
from ..utils.logger import log

def fetch_updated_tickets(config, since_date_str):
    """Busca tickets do Freshdesk atualizados desde uma data específica."""
    log(f"Buscando tickets do Freshdesk atualizados desde {since_date_str}...")
    updated_since = f"{since_date_str}T00:00:00Z"
    url = f"https://{config['FRESHDESK_DOMAIN']}.freshdesk.com/api/v2/tickets"
    params = {'updated_since': updated_since, 'include': 'description', 'order_by': 'updated_at', 'order_type': 'desc'}
    return api_request('GET', url, config['FRESHDESK_AUTH'], params=params) or []

def create_ticket(config, jira_ticket, description_text):
    """Cria um novo ticket no Freshdesk."""
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
    return api_request('POST', url, config['FRESHDESK_AUTH'], json_data=payload)

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
    
def fetch_all_relevant_tickets(config, since_date_str):
    """Busca todos os tickets recentes do Freshdesk para o mapeamento inteligente."""
    log(f"Buscando todos os tickets do Freshdesk desde {since_date_str} para mapeamento...")
    url = f"https://{config['FRESHDESK_DOMAIN']}.freshdesk.com/api/v2/tickets"
    params = {'updated_since': f"{since_date_str}T00:00:00Z", 'include': 'description', 'per_page': 100}
    return api_request('GET', url, config['FRESHDESK_AUTH'], params=params) or []