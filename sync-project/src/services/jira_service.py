# src/services/jira_service.py
"""
Serviço responsável por todas as interações com a API do Jira.
"""
from ..utils.api_client import api_request
from ..utils.logger import log

class TransitionNotFoundError(Exception):
    """Exceção personalizada para quando uma transição do Jira não é encontrada."""
    pass

# Mapeia vários nomes de status do Jira para o mesmo ID de status do Freshdesk
# Freshdesk Padrão: 2=Open, 3=In Progress, 4=Resolved, 5=Closed
JIRA_STATUS_TO_FRESHDESK = {
    'Backlog': 2, 'Tarefas Pendentes': 2, 'To Do': 2, 'A Fazer': 2,
    'In Progress': 3, 'Em andamento': 3, 'Em Análise': 3,
    'Done': 4, 'Concluído': 4, 'Resolvido': 4, 'Feito': 4,
    'Closed': 5, 'Fechado': 5,
}

# Mapeia nomes de prioridade do Jira para o ID de prioridade do Freshdesk
# Freshdesk Padrão: 1=Low, 2=Medium, 3=High, 4=Urgent
JIRA_PRIORITY_TO_FRESHDESK = {
    'Lowest': 1, 'Low': 1, 'Baixa': 1,
    'Medium': 2, 'Média': 2,
    'High': 3, 'Alta': 3,
    'Highest': 4, 'Mais alta': 4, 'Urgente': 4,
}

def fetch_updated_tickets(config, since_date_str, created_since_str=None):
    """
    Busca tickets de um projeto que foram atualizados desde uma data.
    Adiciona um filtro opcional para a data de criação.
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
    # [CORREÇÃO] O campo 'attachment' foi adicionado para buscar anexos gerais.
    params = {'jql': jql, 'fields': 'summary,description,status,comment,updated,created,priority,attachment'}
    response = api_request('GET', url, config['JIRA_AUTH'], params=params)
    return response.get('issues', []) if response else []

def add_comment(config, issue_key, comment_text):
    """Adiciona um comentário a um ticket."""
    log(f"Adicionando comentário ao Jira {issue_key}...")
    url = f"{config['JIRA_URL']}/rest/api/3/issue/{issue_key}/comment"
    payload = {"body": {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": comment_text}]}]}}
    api_request('POST', url, config['JIRA_AUTH'], json_data=payload)

def transition_issue(config, issue_key, transition_name):
    """
    Executa uma transição de status em um ticket.
    Tenta encontrar a transição pelo nome exato (case-insensitive) fornecido.
    """
    log(f"Buscando transição exata '{transition_name}' para o Jira {issue_key}...", 'DEBUG')
    transitions_url = f"{config['JIRA_URL']}/rest/api/3/issue/{issue_key}/transitions"
    
    data = api_request('GET', transitions_url, config['JIRA_AUTH'])
    if not data or 'transitions' not in data: 
        log(f"Não foi possível obter transições disponíveis para {issue_key}.", level='ERROR')
        return False
    
    available_transitions = data.get('transitions', [])
    
    # Busca a transição pelo nome exato, ignorando maiúsculas/minúsculas
    transition_id = next((t['id'] for t in available_transitions if t['name'].lower() == transition_name.lower()), None)

    if transition_id:
        payload = {"transition": {"id": transition_id}}
        response = api_request('POST', transitions_url, config['JIRA_AUTH'], json_data=payload)
        # Retorna True se a requisição foi bem-sucedida (não nula)
        return response is not None
    else:
        # Se não encontrou, retorna False. O sync_service tentará o próximo nome.
        # Logamos as transições disponíveis para facilitar a depuração.
        available_names = [t['name'] for t in available_transitions]
        log(f"Transição '{transition_name}' não encontrada entre as disponíveis: {available_names}", 'DEBUG')
        return False

    if not transition_id:
        log(f"Transição '{transition_name}' não encontrada. Tentando alternativas...", level='WARNING')
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

def _extract_adf_nodes(adf_content, node_type):
    """Função recursiva para encontrar todos os nós de um tipo específico no ADF."""
    nodes = []
    if isinstance(adf_content, dict):
        if adf_content.get('type') == node_type:
            nodes.append(adf_content)
        if 'content' in adf_content:
            nodes.extend(_extract_adf_nodes(adf_content['content'], node_type))
    elif isinstance(adf_content, list):
        for item in adf_content:
            nodes.extend(_extract_adf_nodes(item, node_type))
    return nodes

def extract_attachment_refs_from_adf(adf_content):
    """Extrai referências de anexos da descrição (estrutura ADF) do Jira."""
    media_nodes = _extract_adf_nodes(adf_content, 'media')
    attachments = []
    for node in media_nodes:
        attrs = node.get('attrs', {})
        if attrs.get('type') == 'file':
            attachment_id = attrs.get('id')
            if attachment_id:
                attachments.append({'id': attachment_id})
    return attachments

def get_attachment_details(config, attachment_id):
    """Busca os detalhes de um anexo, como nome do arquivo e URL de conteúdo."""
    log(f"Buscando detalhes do anexo do Jira ID: {attachment_id}", 'DEBUG')
    url = f"{config['JIRA_URL']}/rest/api/3/attachment/{attachment_id}"
    return api_request('GET', url, config['JIRA_AUTH'])

def download_attachment(config, content_url):
    """
    Baixa o conteúdo de um anexo do Jira a partir de uma URL de conteúdo.
    """
    if not content_url:
        log("URL de conteúdo vazia. Não é possível baixar.", 'WARNING')
        return None

    log(f"Baixando anexo do Jira a partir da URL: {content_url}", 'DEBUG')
    auth = (config['JIRA_USER_EMAIL'], config['JIRA_API_TOKEN'])
    
    
    # --- MUDANÇA PRINCIPAL AQUI ---
    # Passamos expect_json=False para que a api_request retorne os bytes do arquivo.
    content = api_request('GET', content_url, auth, expect_json=False)
    
    if content:
        log(f"Anexo baixado com sucesso. Tamanho: {len(content)} bytes.", 'DEBUG')
    else:
        log(f"Falha ao baixar anexo de {content_url}", 'WARNING')
    
    return content

def get_ticket_general_attachments(jira_ticket):
    """
    Obtém os IDs de anexos de um ticket do Jira, extraindo do campo geral `fields.attachment`.
    Retorna uma lista de IDs de anexos (strings).
    """
    attachment_field = jira_ticket['fields'].get('attachment')
    if not attachment_field:
        return []
    
    return [item['id'] for item in attachment_field]