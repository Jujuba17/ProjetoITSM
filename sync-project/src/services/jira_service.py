# src/services/jira_service.py
"""
Serviço responsável por todas as interações com a API do Jira.
"""
from ..utils.api_client import api_request
from ..utils.logger import log

def fetch_updated_tickets(config, since_date_str, created_since_str=None):
    """
    Busca tickets de um projeto que foram atualizados desde uma data.
    [CORRIGIDO] Adiciona um filtro opcional para a data de criação.
    """
    log(f"Buscando tickets do Jira atualizados desde {since_date_str}...")
    
    # Constrói a JQL base
    jql_parts = [
        f"project = '{config['JIRA_PROJECT_KEY']}'",
        f"updated >= '{since_date_str}'"
    ]
    
    # Adiciona o filtro de data de criação se ele for fornecido
    if created_since_str:
        jql_parts.append(f"created >= '{created_since_str}'")
        log(f"Aplicando filtro adicional: criados desde {created_since_str}", 'DEBUG')

    jql = " AND ".join(jql_parts)
    
    url = f"{config['JIRA_URL']}/rest/api/3/search"
    params = {'jql': jql, 'fields': 'summary,description,status,comment,updated,created,priority'}
    response = api_request('GET', url, config['JIRA_AUTH'], params=params)
    return response.get('issues', []) if response else []
def add_comment(config, issue_key, comment_text):
    """Adiciona um comentário a um ticket."""
    log(f"Adicionando comentário ao Jira {issue_key}...")
    url = f"{config['JIRA_URL']}/rest/api/3/issue/{issue_key}/comment"
    payload = {"body": {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": comment_text}]}]}}
    api_request('POST', url, config['JIRA_AUTH'], json_data=payload)

def transition_issue(config, issue_key, transition_name):
    """Executa uma transição de status em um ticket."""
    log(f"Tentando transição '{transition_name}' para o Jira {issue_key}...")
    transitions_url = f"{config['JIRA_URL']}/rest/api/3/issue/{issue_key}/transitions"
    data = api_request('GET', transitions_url, config['JIRA_AUTH'])
    
    if not data or 'transitions' not in data: 
        log(f"Nenhuma transição disponível para {issue_key}.", level='ERROR')
        return False
    
    available = data['transitions']
    transition_id = next((t['id'] for t in available if t['name'].lower() == transition_name.lower()), None)

    if not transition_id:
        log(f"Transição '{transition_name}' não encontrada. Tentando alternativas...", level='WARNING')
        # Lógica de fallback simplificada para encontrar transições similares
        completion_terms = ["done", "conclu", "finish", "complet", "resolv"]
        if any(term in transition_name.lower() for term in completion_terms):
            for t in available:
                if any(term in t['name'].lower() for term in completion_terms):
                    transition_id = t['id']
                    log(f"Usando transição alternativa '{t['name']}' para conclusão.", level='WARNING')
                    break

    if not transition_id:
        log(f"Nenhuma transição compatível encontrada para '{transition_name}'.", level='ERROR')
        return False

    return api_request('POST', transitions_url, config['JIRA_AUTH'], json_data={"transition": {"id": transition_id}}) is not None

def extract_description(jira_ticket):
    """Extrai o texto puro da descrição de um ticket do Jira (formato ADF)."""
    description_obj = jira_ticket['fields'].get('description')
    if not description_obj: return ""
    try:
        content_list = description_obj['content']
        paragraphs = []
        for item in content_list:
            if item.get('type') == 'paragraph':
                para_text = "".join(part.get('text', '') for part in item.get('content', []))
                paragraphs.append(para_text)
        return "\n".join(paragraphs).strip()
    except (KeyError, TypeError):
        return str(description_obj).strip()