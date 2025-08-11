# src/utils/text_utils.py
"""
Funções utilitárias para manipulação e normalização de texto.
"""
import re

def strip_html_tags(html_string: str) -> str:
    """Remove tags HTML de uma string."""
    if not html_string:
        return ""
    return re.sub(r'<[^>]*>', '', html_string)

def normalize_text(text: str) -> str:
    """Normaliza o texto para uma comparação mais robusta."""
    if not text:
        return ""
    # Remove pontuação, mantém letras, números e espaços
    text_no_punct = re.sub(r'[^\w\s]', '', text)
    # Substitui múltiplos espaços por um único, remove espaços no início/fim e converte para minúsculas
    return re.sub(r'\s+', ' ', text_no_punct).strip().lower()

# --- CÓDIGO NOVO ADICIONADO AQUI ---

def extract_text_from_adf(adf_content: dict or str) -> str:
    """
    Extrai o texto puro de uma estrutura ADF (Atlassian Document Format).
    Lida com parágrafos, nós de texto e quebras de linha de forma recursiva.

    Args:
        adf_content: O conteúdo ADF, que pode ser um dicionário ou, em casos legados, uma string.

    Returns:
        O texto extraído como uma string limpa.
    """
    if not adf_content:
        return ""

    # Caso 1: O conteúdo já é uma string simples (não ADF).
    if isinstance(adf_content, str):
        return adf_content.strip()

    # Caso 2: O conteúdo é um dicionário (formato ADF).
    if isinstance(adf_content, dict):
        try:
            # A função auxiliar _parse_adf_nodes fará o trabalho pesado.
            all_parts = _parse_adf_nodes(adf_content.get('content', []))
            # Junta as partes e limpa quebras de linha duplicadas ou espaços extras.
            return re.sub(r'\n{2,}', '\n\n', "".join(all_parts)).strip()
        except (AttributeError, TypeError, KeyError):
            # Em caso de formato inesperado, retorna uma representação em string como fallback.
            return str(adf_content).strip()
    
    return "" # Fallback para outros tipos de dados inesperados.


def _parse_adf_nodes(nodes: list) -> list:
    """
    Função auxiliar recursiva para percorrer os nós do ADF e retornar uma lista de strings.
    """
    text_parts = []
    if not isinstance(nodes, list):
        return text_parts

    for node in nodes:
        if not isinstance(node, dict):
            continue
            
        node_type = node.get('type')

        # Extrai texto de nós de texto.
        if node_type == 'text':
            text_parts.append(node.get('text', ''))
        
        # Converte quebras de linha forçadas.
        elif node_type == 'hardBreak':
            text_parts.append('\n')

        # Se o nó atual tiver mais conteúdo (como um parágrafo, item de lista, etc.),
        # chama a função recursivamente para processar os nós filhos.
        if 'content' in node and node['content']:
            text_parts.extend(_parse_adf_nodes(node['content']))
            
            # Adiciona uma quebra de linha após nós de bloco para garantir a separação.
            block_nodes = ['paragraph', 'heading', 'blockquote', 'listItem']
            if node_type in block_nodes:
                 text_parts.append('\n')

    return text_parts