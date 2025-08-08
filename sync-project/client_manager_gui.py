import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
import requests
import shutil
from requests.auth import HTTPBasicAuth

# --- LÓGICA DE TESTE DE CONEXÃO ---
# (Sem alterações aqui, pois os novos campos não afetam o teste de autenticação)
def test_jira_connection(url, user_email, api_token, project_key):
    """Testa a conexão com o Jira e retorna (status, mensagem)."""
    if not all([url, user_email, api_token, project_key]):
        return False, "Todos os campos do Jira devem ser preenchidos."
    try:
        response = requests.get(
            f"{url}/rest/api/3/project/{project_key}",
            headers={"Accept": "application/json"},
            auth=HTTPBasicAuth(user_email, api_token),
            timeout=10
        )
        response.raise_for_status()
        return True, "Jira: Conexão bem-sucedida."
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            return False, "Jira: Falha na autenticação (Email ou Token inválido)."
        if e.response.status_code == 404:
            return False, f"Jira: Conexão OK, mas o projeto '{project_key}' não foi encontrado."
        return False, f"Jira: Erro HTTP - {e}"
    except requests.exceptions.RequestException as e:
        return False, f"Jira: Erro de Conexão - {e}"

def test_freshdesk_connection(domain, api_key):
    """Testa a conexão com o Freshdesk e retorna (status, mensagem)."""
    if not all([domain, api_key]):
        return False, "Todos os campos do Freshdesk devem ser preenchidos."
    try:
        response = requests.get(
            f"https://{domain}.freshdesk.com/api/v2/tickets?per_page=1",
            auth=(api_key, "X"),
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        response.raise_for_status()
        return True, "Freshdesk: Conexão bem-sucedida."
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            return False, "Freshdesk: Falha na autenticação (Domínio ou Chave da API inválida)."
        return False, f"Freshdesk: Erro HTTP - {e}"
    except requests.exceptions.RequestException as e:
        return False, f"Freshdesk: Erro de Conexão - {e}"

# --- FUNÇÕES DA INTERFACE GRÁFICA ---

def edit_client_window(client_name, on_close_callback):
    """
    [ATUALIZADO] Abre a janela de edição com os campos de Company ID, Sync Comments e Sync Attachments.
    """
    config_path = os.path.join('clients', client_name, 'config.json')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except Exception as e:
        messagebox.showerror("Erro de Leitura", f"Não foi possível ler o arquivo de configuração: {e}")
        return

    edit_window = tk.Toplevel(root)
    edit_window.title(f"Editando Cliente: {client_name}")
    edit_window.geometry("600x650") # Aumenta a altura da janela

    frame = ttk.Frame(edit_window, padding="10")
    frame.pack(fill="both", expand=True)

    entries = {}
    labels_and_keys = {
        "URL do Jira:": "JIRA_URL", "Email do Usuário Jira:": "JIRA_USER_EMAIL",
        "Token da API Jira:": "JIRA_API_TOKEN", "Chave do Projeto Jira:": "JIRA_PROJECT_KEY",
        "Domínio do Freshdesk:": "FRESHDESK_DOMAIN", "Chave da API Freshdesk:": "FRESHDESK_API_KEY",
        "ID da Companhia no Freshdesk:": "FRESHDESK_COMPANY_ID", # Novo campo
        "Dias de Retrocesso para Mapeamento (1-999):": "MAPPING_LOOKBACK_DAYS",
        "Dias de Retrocesso para Sincronização (1-999):": "SYNC_DAYS_AGO"
    }

    ttk.Label(frame, text="Nome do Cliente:", font=("Arial", 10, "bold")).grid(row=0, column=0, sticky="w", pady=2)
    ttk.Label(frame, text=client_name).grid(row=0, column=1, sticky="w", pady=2)

    current_row = 1
    for text, key in labels_and_keys.items():
        ttk.Label(frame, text=text).grid(row=current_row, column=0, sticky="w", pady=2)
        entry = ttk.Entry(frame, width=60)
        
        default_value = ""
        if key == "MAPPING_LOOKBACK_DAYS": default_value = 30
        elif key == "SYNC_DAYS_AGO": default_value = 7
        
        value = config.get(key, default_value)
        entry.insert(0, str(value) if value is not None else "")
        
        entry.grid(row=current_row, column=1, sticky="ew", pady=2)
        entries[key] = entry
        current_row += 1
    
    # Checkboxes
    smart_mapping_var = tk.BooleanVar(value=config.get("ENABLE_SMART_MAPPING", True))
    sync_comments_var = tk.BooleanVar(value=config.get("SYNC_COMMENTS", True))
    sync_attachments_var = tk.BooleanVar(value=config.get("SYNC_ATTACHMENTS", True))
    
    ttk.Checkbutton(frame, text="Habilitar Mapeamento Inteligente", variable=smart_mapping_var).grid(row=current_row, columnspan=2, pady=5, sticky="w")
    current_row += 1
    ttk.Checkbutton(frame, text="Sincronizar Comentários", variable=sync_comments_var).grid(row=current_row, columnspan=2, pady=5, sticky="w")
    current_row += 1
    ttk.Checkbutton(frame, text="Sincronizar Anexos", variable=sync_attachments_var).grid(row=current_row, columnspan=2, pady=5, sticky="w")
    current_row += 1

    def test_form_connection():
        jira_status, jira_msg = test_jira_connection(
            entries["JIRA_URL"].get(), entries["JIRA_USER_EMAIL"].get(),
            entries["JIRA_API_TOKEN"].get(), entries["JIRA_PROJECT_KEY"].get()
        )
        fd_status, fd_msg = test_freshdesk_connection(
            entries["FRESHDESK_DOMAIN"].get(), entries["FRESHDESK_API_KEY"].get()
        )
        message = f"{jira_msg}\n{fd_msg}"
        if jira_status and fd_status: messagebox.showinfo("Resultado do Teste", message, parent=edit_window)
        else: messagebox.showerror("Resultado do Teste", message, parent=edit_window)

    def save_changes():
        try:
            mapping_days = int(entries["MAPPING_LOOKBACK_DAYS"].get().strip())
            sync_days = int(entries["SYNC_DAYS_AGO"].get().strip())
            if not (1 <= mapping_days <= 999 and 1 <= sync_days <= 999): raise ValueError()
            
            # Validação para o Company ID (opcional, mas se preenchido, deve ser número)
            company_id_str = entries["FRESHDESK_COMPANY_ID"].get().strip()
            company_id = int(company_id_str) if company_id_str else None

        except (ValueError, KeyError):
            messagebox.showerror("Erro de Validação", "Os campos de dias e o ID da companhia devem ser números válidos.", parent=edit_window)
            return
            
        new_config = config.copy()
        for key, entry in entries.items():
            if key not in ["MAPPING_LOOKBACK_DAYS", "SYNC_DAYS_AGO", "FRESHDESK_COMPANY_ID"]:
                 new_config[key] = entry.get().strip() or None
        
        new_config["MAPPING_LOOKBACK_DAYS"] = mapping_days
        new_config["SYNC_DAYS_AGO"] = sync_days
        new_config["FRESHDESK_COMPANY_ID"] = company_id
        new_config["ENABLE_SMART_MAPPING"] = smart_mapping_var.get()
        new_config["SYNC_COMMENTS"] = sync_comments_var.get()
        new_config["SYNC_ATTACHMENTS"] = sync_attachments_var.get()
        new_config["LOG_LEVEL"] = "INFO"

        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(new_config, f, indent=4)
            messagebox.showinfo("Sucesso", f"Cliente '{client_name}' atualizado com sucesso!", parent=edit_window)
            edit_window.destroy()
            on_close_callback()
        except Exception as e:
            messagebox.showerror("Erro de Arquivo", f"Não foi possível salvar as alterações: {e}", parent=edit_window)

    button_frame = ttk.Frame(frame)
    button_frame.grid(row=current_row, columnspan=2, pady=20)
    ttk.Button(button_frame, text="Testar Conexão", command=test_form_connection).pack(side="left", padx=10)
    ttk.Button(button_frame, text="Salvar Alterações", command=save_changes).pack(side="left", padx=10)


def delete_client(client_name, client_frame, on_delete_callback):
    """Pede confirmação e deleta o cliente."""
    if messagebox.askyesno("Confirmar Exclusão", f"Você tem certeza que deseja excluir o cliente '{client_name}'?", icon='warning'):
        try:
            shutil.rmtree(os.path.join('clients', client_name))
            client_frame.destroy()
            on_delete_callback()
            messagebox.showinfo("Sucesso", f"Cliente '{client_name}' excluído com sucesso.")
        except Exception as e:
            messagebox.showerror("Erro", f"Não foi possível excluir o cliente: {e}")

def list_clients():
    """Abre a janela para listar, editar, excluir e TESTAR clientes."""
    list_window = tk.Toplevel(root)
    list_window.title("Clientes Cadastrados")
    list_window.geometry("600x500")

    main_frame = ttk.Frame(list_window)
    main_frame.pack(fill="both", expand=True)

    def refresh_list():
        for widget in scrollable_frame.winfo_children(): widget.destroy()
        populate_list()
        update_scroll_region()

    header_frame = ttk.Frame(main_frame, padding=5)
    header_frame.pack(fill="x", side="top")
    ttk.Label(header_frame, text="Clientes:", font=("Arial", 12, "bold")).pack(side="left")
    ttk.Button(header_frame, text="Adicionar Novo", command=lambda: open_new_client_window(refresh_list)).pack(side="right")
    
    ttk.Separator(main_frame).pack(fill='x', pady=5)
    
    canvas = tk.Canvas(main_frame)
    scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
    scrollable_frame = ttk.Frame(canvas)
    scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    
    def update_scroll_region():
        canvas.update_idletasks()
        canvas.configure(scrollregion=canvas.bbox("all"))

    def test_saved_config(client_name):
        config_path = os.path.join('clients', client_name, 'config.json')
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except Exception as e:
            messagebox.showerror("Erro", f"Não foi possível ler o config.json: {e}", parent=list_window)
            return

        jira_status, jira_msg = test_jira_connection(
            config.get("JIRA_URL"), config.get("JIRA_USER_EMAIL"),
            config.get("JIRA_API_TOKEN"), config.get("JIRA_PROJECT_KEY")
        )
        fd_status, fd_msg = test_freshdesk_connection(
            config.get("FRESHDESK_DOMAIN"), config.get("FRESHDESK_API_KEY")
        )

        message = f"Cliente: {client_name}\n\n{jira_msg}\n{fd_msg}"
        if jira_status and fd_status: messagebox.showinfo("Resultado do Teste", message, parent=list_window)
        else: messagebox.showerror("Resultado do Teste", message, parent=list_window)

    def populate_list():
        try:
            clients = sorted([f for f in os.listdir('clients') if os.path.isdir(os.path.join('clients', f))])
        except FileNotFoundError:
            clients = []

        if not clients:
            ttk.Label(scrollable_frame, text="Nenhum cliente cadastrado.", padding=10).pack()
            return

        for client_name in clients:
            client_frame = ttk.Frame(scrollable_frame, padding=5, relief="groove", borderwidth=1)
            client_frame.pack(fill="x", expand=True, padx=10, pady=5)
            
            ttk.Label(client_frame, text=client_name, font=("Arial", 11, "bold")).pack(side="left", padx=10)
            delete_btn = ttk.Button(client_frame, text="Excluir", command=lambda name=client_name, frame=client_frame: delete_client(name, frame, update_scroll_region))
            delete_btn.pack(side="right", padx=5)
            edit_btn = ttk.Button(client_frame, text="Editar", command=lambda name=client_name: edit_client_window(name, refresh_list))
            edit_btn.pack(side="right", padx=5)
            test_btn = ttk.Button(client_frame, text="Testar", command=lambda name=client_name: test_saved_config(name))
            test_btn.pack(side="right", padx=5)

    populate_list()
    update_scroll_region()

def open_new_client_window(on_close_callback=None):
    """
    [ATUALIZADO] Abre a janela para criar um novo cliente com os campos de Company ID e sync.
    """
    if not os.path.exists('clients'): os.makedirs('clients')

    new_window = tk.Toplevel(root)
    new_window.title("Cadastrar Novo Cliente")
    new_window.geometry("600x650") # Aumenta a altura da janela
    
    if on_close_callback:
        new_window.protocol("WM_DELETE_WINDOW", lambda: (on_close_callback(), new_window.destroy()))

    frame = ttk.Frame(new_window, padding="10")
    frame.pack(fill="both", expand=True)

    entries = {}
    labels = {
        "client_name": "Nome do Cliente (sem espaços):", "JIRA_URL": "URL do Jira:",
        "JIRA_USER_EMAIL": "Email do Usuário Jira:", "JIRA_API_TOKEN": "Token da API Jira:",
        "JIRA_PROJECT_KEY": "Chave do Projeto Jira:", "FRESHDESK_DOMAIN": "Domínio do Freshdesk:",
        "FRESHDESK_API_KEY": "Chave da API Freshdesk:",
        "FRESHDESK_COMPANY_ID": "ID da Companhia no Freshdesk:", # Novo campo
        "MAPPING_LOOKBACK_DAYS": "Dias de Retrocesso para Mapeamento (1-999):",
        "SYNC_DAYS_AGO": "Dias de Retrocesso para Sincronização (1-999):"
    }

    current_row = 0
    for key, text in labels.items():
        ttk.Label(frame, text=text).grid(row=current_row, column=0, sticky="w", pady=2)
        entry = ttk.Entry(frame, width=60)
        entry.grid(row=current_row, column=1, sticky="ew", pady=2)
        entries[key] = entry
        current_row += 1
    
    entries["MAPPING_LOOKBACK_DAYS"].insert(0, "30")
    entries["SYNC_DAYS_AGO"].insert(0, "7")
    
    # Checkboxes inicializados como True (marcados)
    smart_mapping_var = tk.BooleanVar(value=False)
    sync_comments_var = tk.BooleanVar(value=False)
    sync_attachments_var = tk.BooleanVar(value=False)

    ttk.Checkbutton(frame, text="Habilitar Mapeamento Inteligente", variable=smart_mapping_var).grid(row=current_row, columnspan=2, pady=5, sticky="w")
    current_row += 1
    ttk.Checkbutton(frame, text="Sincronizar Comentários", variable=sync_comments_var).grid(row=current_row, columnspan=2, pady=5, sticky="w")
    current_row += 1
    ttk.Checkbutton(frame, text="Sincronizar Anexos", variable=sync_attachments_var).grid(row=current_row, columnspan=2, pady=5, sticky="w")
    current_row += 1

    def test_current_connection():
        jira_status, jira_msg = test_jira_connection(entries["JIRA_URL"].get(), entries["JIRA_USER_EMAIL"].get(), entries["JIRA_API_TOKEN"].get(), entries["JIRA_PROJECT_KEY"].get())
        fd_status, fd_msg = test_freshdesk_connection(entries["FRESHDESK_DOMAIN"].get(), entries["FRESHDESK_API_KEY"].get())
        message = f"{jira_msg}\n{fd_msg}"
        if jira_status and fd_status: messagebox.showinfo("Resultado do Teste", message, parent=new_window)
        else: messagebox.showerror("Resultado do Teste", message, parent=new_window)

    def save_client():
        data = {key: entry.get().strip() for key, entry in entries.items()}

        if not data["client_name"] or ' ' in data["client_name"]:
            messagebox.showerror("Erro", "Nome do cliente é obrigatório e não pode conter espaços.", parent=new_window)
            return

        try:
            mapping_days = int(data["MAPPING_LOOKBACK_DAYS"])
            sync_days = int(data["SYNC_DAYS_AGO"])
            if not (1 <= mapping_days <= 999 and 1 <= sync_days <= 999): raise ValueError()
            
            # Validação para o Company ID (opcional, mas se preenchido, deve ser número)
            company_id_str = data["FRESHDESK_COMPANY_ID"]
            company_id = int(company_id_str) if company_id_str else None

        except (ValueError, KeyError):
            messagebox.showerror("Erro de Validação", "Os campos de dias e o ID da companhia devem ser números válidos.", parent=new_window)
            return

        text_fields = {k: v for k, v in data.items() if k not in ["client_name", "MAPPING_LOOKBACK_DAYS", "SYNC_DAYS_AGO", "FRESHDESK_COMPANY_ID"]}
        if not all(text_fields.values()):
             messagebox.showerror("Erro", "Todos os campos de configuração de texto são obrigatórios.", parent=new_window)
             return

        client_path = os.path.join('clients', data["client_name"])
        if os.path.exists(client_path):
            messagebox.showerror("Erro", f"Cliente '{data['client_name']}' já existe.", parent=new_window)
            return

        config_data = {key: val for key, val in data.items() if key != "client_name"}
        
        config_data["MAPPING_LOOKBACK_DAYS"] = mapping_days
        config_data["SYNC_DAYS_AGO"] = sync_days
        config_data["FRESHDESK_COMPANY_ID"] = company_id
        config_data["ENABLE_SMART_MAPPING"] = smart_mapping_var.get()
        config_data["SYNC_COMMENTS"] = sync_comments_var.get()
        config_data["SYNC_ATTACHMENTS"] = sync_attachments_var.get()
        config_data["LOG_LEVEL"] = "INFO"

        try:
            os.makedirs(client_path)
            with open(os.path.join(client_path, 'config.json'), 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=4)
            messagebox.showinfo("Sucesso", f"Cliente '{data['client_name']}' salvo!", parent=new_window)
            new_window.destroy()
            if on_close_callback: on_close_callback()
        except Exception as e:
            messagebox.showerror("Erro de Arquivo", f"Não foi possível salvar: {e}", parent=new_window)
    
    button_frame = ttk.Frame(frame)
    button_frame.grid(row=current_row, columnspan=2, pady=20)
    ttk.Button(button_frame, text="Testar Conexão", command=test_current_connection).pack(side="left", padx=10)
    ttk.Button(button_frame, text="Salvar Cliente", command=save_client).pack(side="left", padx=10)

# --- Janela Principal ---
root = tk.Tk()
root.title("Gerenciador de Clientes - Sincronizador")
root.geometry("450x250")
root.eval('tk::PlaceWindow . center')

style = ttk.Style(root)
style.theme_use('clam')

main_frame = ttk.Frame(root, padding=20)
main_frame.pack(expand=True, fill="both")

ttk.Label(main_frame, text="Gerenciador de Clientes", font=("Arial", 16, "bold")).pack(pady=10)
ttk.Button(main_frame, text="Gerenciar Clientes", command=list_clients, width=30).pack(pady=10, ipady=5)

root.mainloop()