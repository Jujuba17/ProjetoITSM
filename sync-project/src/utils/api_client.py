# src/utils/api_client.py
import requests
from .logger import log

def api_request(method, url, auth, params=None, json_data=None, data=None, files=None, raise_for_status=False):
    
    """
    Realiza uma requisição de API com tratamento de erros centralizado.

    Args:
        method (str): Método HTTP (GET, POST, PUT, DELETE).
        url (str): URL do endpoint da API.
        auth (tuple): Tupla de autenticação (ex: (email, token)).
        params (dict, optional): Parâmetros de URL.
        json_data (dict, optional): Corpo da requisição em formato JSON.
        data (dict, optional): Corpo da requisição em formato form-data.
        files (dict, optional): Arquivos para upload.
        raise_for_status (bool, optional): Se True, lança uma exceção para códigos de erro HTTP (4xx/5xx).

    Returns:
        dict or list or None: A resposta da API em formato JSON, ou None em caso de erro de decodificação.
        Pode lançar exceções se raise_for_status for True ou em erros de rede.
    """
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    }
    # Remove Content-Type se estivermos enviando arquivos (form-data)
    if files:
        del headers['Content-Type']

    log(f"API Request: {method} {url}", 'DEBUG')

    try:
        response = requests.request(
            method, url, auth=auth, headers=headers, params=params,
            json=json_data, data=data, files=files, timeout=30
        )
        log(f"API Response Status: {response.status_code}", 'DEBUG')

        if raise_for_status:
            response.raise_for_status()  # Lançará uma exceção HTTPError para status 4xx/5xx

        # Se for uma resposta bem-sucedida, mas vazia (ex: 204 No Content), retorne o objeto de resposta
        if response.status_code == 204:
            return response

        return response.json()
    except requests.exceptions.HTTPError as e:
        log(f"[ERROR] Erro HTTP para {method} {url}: {e.response.status_code} - {e.response.text}", 'ERROR')
        raise  # Relança a exceção para que o chamador possa tratá-la
    except requests.exceptions.RequestException as e:
        log(f"[ERROR] Erro de rede na API para {method} {url}: {e}", 'ERROR')
        raise  # Relança a exceção
    except ValueError:  # JSONDecodeError herda de ValueError
        log(f"[ERROR] Falha ao decodificar a resposta JSON da API para {method} {url}. Conteúdo: {response.text}", 'ERROR')
        return None