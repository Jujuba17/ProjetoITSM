# src/utils/api_client.py
"""
Cliente de API genérico para realizar requisições HTTP.
"""
import requests
import json
from .logger import log

def api_request(method, url, auth, json_data=None, params=None):
    """
    Função genérica para realizar requisições de API, com logging e tratamento de erro.
    """
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    
    log(f"API Request: {method} {url}", level='DEBUG')
    
    try:
        response = requests.request(
            method, url, json=json_data, params=params, 
            auth=auth, headers=headers, timeout=30
        )
        
        log(f"API Response Status: {response.status_code}", level='DEBUG')
        response.raise_for_status()
        
        return response.json() if response.content else None
            
    except requests.exceptions.Timeout:
        log(f"Timeout na requisição {method} {url}", level='ERROR')
        return None
    except json.JSONDecodeError:
        log(f"Resposta não é JSON válido: {response.text[:100]}...", level='WARNING')
        return None
    except requests.exceptions.RequestException as e:
        log(f"Erro na API para {method} {url}: {e}", level='ERROR')
        if hasattr(e, 'response') and e.response is not None:
            log(f"Status: {e.response.status_code}, Detalhes: {e.response.text[:500]}", level='ERROR')
        return None