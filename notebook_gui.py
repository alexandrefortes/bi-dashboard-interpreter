import ipywidgets as widgets
from IPython.display import display, clear_output, HTML
import notebook_helper
import reporter
import install_deps
import sys
import io
import os
import webbrowser

# Widget de Saída Global (para capturar prints de configuração)
out = widgets.Output(layout={'border': '1px solid #ddd', 'height': '250px', 'overflow_y': 'scroll'})

# Widget de Saída de Execução (para logs do PowerShell)
out_exec = widgets.Output(layout={'border': '1px solid #ddd', 'height': '100px', 'overflow_y': 'scroll'})

def capture_output(func):
    """Decorator para capturar stdout/stderr dentro do widget global (out)."""
    def wrapper(*args, **kwargs):
        with out:
            # Limpa output imediatamente para dar feedback visual de clique (flash)
            out.clear_output(wait=False) 
            try:
                func(*args, **kwargs)
            except Exception as e:
                print(f"❌ Erro: {e}")
    return wrapper

def capture_exec_output(func):
    """Decorator para capturar stdout/stderr dentro do widget de execução (out_exec)."""
    def wrapper(*args, **kwargs):
        with out_exec:
            # Limpa output imediatamente
            out_exec.clear_output(wait=False) 
            try:
                func(*args, **kwargs)
            except Exception as e:
                print(f"❌ Erro: {e}")
    return wrapper

# --- Botões e Ações ---

url_area = widgets.Textarea(
    value=notebook_helper.load_urls(), # Carrega URLs atuais
    placeholder='Cole suas URLs aqui (uma por linha)...',
    description='URLs:',
    layout={'width': '98%', 'height': '150px'}
)

# Mensagem final padronizada
FINAL_MSG = "\n🚀 \033[1mTudo pronto! Clique em um dos botões de Execução (Lote ou Sequencial) abaixo para iniciar.\033[0m"

@capture_output
def on_click_update(b):
    urls = url_area.value
    if not urls.strip():
        print("⚠️ Por favor, insira pelo menos uma URL.")
        return
    
    print("\n--- 🔄 Atualizar Painéis (Smart Update) ---")
    notebook_helper.define_urls(urls, mode="smart")
    
    # Mostra backup
    old_urls = notebook_helper.get_old_urls_content()
    if old_urls:
        print("\n📜 [Backup] Conteúdo anterior de urls.json (Recuperado do backup mais recente):")
        print(old_urls)
    
    # Mensagem final em Negrito
    print(FINAL_MSG)

@capture_output
def on_click_save_simple(b):
    urls = url_area.value
    if not urls.strip():
        print("⚠️ Por favor, insira pelo menos uma URL.")
        return

    print("\n--- 💾 Salvar URLs (Sem Limpeza) ---")
    notebook_helper.define_urls(urls, mode="simple")
    
    # Mostra backup também aqui, por segurança
    old_urls = notebook_helper.get_old_urls_content()
    if old_urls:
         print("\n📜 [Backup] Conteúdo anterior de urls.json (Recuperado do backup mais recente):")
         print(old_urls)

    # Mensagem final em Negrito
    print(FINAL_MSG)

@capture_output
def on_click_reset(b):
    print("\n--- ☢️ Reset Total ---")
    notebook_helper.reset_all()
    print("\n✅ Ambiente limpo. Você pode começar do zero.")

@capture_output
def on_click_report(b):
    print("\n--- 📊 Gerar Relatório ---")
    path = reporter.generate_report()
    if path:
        # Usa pathlib para obter URI absoluto correto
        from pathlib import Path
        abs_path = Path(path).absolute()
        abs_uri = abs_path.as_uri()
        
        if sys.platform == 'win32':
            # Windows: os.startfile é mais robusto para abrir arquivos locais
            try:
                os.startfile(str(abs_path))
                print("✅ Comando de abertura enviado (Windows Shell).")
            except Exception as e:
                print(f"⚠️ Erro no startfile: {e}")
        else:
            # Linux/Mac: Webbrowser
            try:
                webbrowser.open(abs_uri)
                print("✅ Comando de abertura enviado (Webbrowser).")
            except Exception as e:
                print(f"⚠️ Erro no webbrowser: {e}")
            
        display(HTML(f"👉 <a href='bi_catalog_report/index.html' target='_blank'>Clique aqui se não abrir (Link Relativo)</a>"))

def run_powershell(command):
    """Executa comando em nova janela PowerShell (User Friendly)."""
    print(f"\n--- 🚀 Iniciando: {command} ---")
    if sys.platform == 'win32':
        try:
            # start powershell -NoExit -Command "..."
            # -NoExit: Mantém a janela aberta após o fim
            cmd = f'start powershell -NoExit -Command "{command}"'
            os.system(cmd)
            print("✅ Nova janela do PowerShell aberta! Verifique a barra de tarefas.")
        except Exception as e:
            print(f"❌ Erro ao abrir PowerShell: {e}")
    else:
         print(f"⚠️ Funcionalidade exclusiva para Windows. No terminal, rode: {command}")

@capture_exec_output
def on_click_run_batch(b):
    run_powershell("python batch_main.py")

@capture_exec_output
def on_click_run_seq(b):
    run_powershell("python main.py")

# Layout comum para botões (para ficarem largos e legíveis)
btn_layout = widgets.Layout(width='48%')

# Botões de Configuração
btn_update = widgets.Button(
    description='Remover URLs acima do Catálogo (CUIDADO!)',
    button_style='danger', 
    icon='minus-circle',
    tooltip='Remove todo o histórico (pastas/logs) das URLs listadas acima para recomeçar do zero.',
    layout=btn_layout
)
btn_update.style.font_weight = 'bold'
btn_update.on_click(on_click_update)

btn_save_simple = widgets.Button(
    description='Catalogar URLs Acima',
    button_style='', # Customizado para texto preto
    icon='plus-circle',
    tooltip='Salva as URLs na fila de processamento sem apagar o que já foi feito. Se parou no meio, use este.',
    layout=btn_layout
)
btn_save_simple.style.button_color = '#5cb85c' # Green Success (Bootstrap)
btn_save_simple.style.text_color = 'black'
btn_save_simple.style.font_weight = 'bold'
btn_save_simple.on_click(on_click_save_simple)

btn_reset = widgets.Button(
    description='Reset de Fábrica (CUIDADO! Esse botão apaga tudo que já foi catalogado!)',
    button_style='danger',
    icon='trash',
    tooltip='Cuidado: Apaga TODAS as execuções, relatórios e limpa a lista de URLs.',
    layout=btn_layout
)
btn_reset.style.font_weight = 'bold'
btn_reset.on_click(on_click_reset)

btn_report = widgets.Button(
    description='Gerar/Abrir Relatório (HTML)',
    button_style='', # Customizado para texto preto
    icon='table',
    tooltip='Gera o site estático com o catálogo atual e abre no navegador.',
    layout=btn_layout
)
btn_report.style.button_color = '#5bc0de' # Info Blue (Bootstrap)
btn_report.style.text_color = 'black'
btn_report.style.font_weight = 'bold'
btn_report.on_click(on_click_report)

# Botões de Execução (PowerShell) - Customizados (Laranja + Texto Preto)
btn_run_batch = widgets.Button(
    description='▶️ Executar Batch (Lote)',
    button_style='', # Remove estilo padrão para permitir customização total
    icon='rocket',
    tooltip='Abre PowerShell e processa todas as URLs em paralelo (Rápido).',
    layout=btn_layout
)
btn_run_batch.style.button_color = '#ffae00' # Laranja intenso
btn_run_batch.style.text_color = 'black'
btn_run_batch.style.font_weight = 'bold'
btn_run_batch.on_click(on_click_run_batch)

btn_run_seq = widgets.Button(
    description='▶️ Executar Sequencial',
    button_style='',
    icon='play',
    tooltip='Abre PowerShell e processa uma URL por vez (Mais lento, para debug).',
    layout=btn_layout
)
btn_run_seq.style.font_weight = 'bold'
btn_run_seq.on_click(on_click_run_seq)


def check_dependencies():
    """Verifica e instala dependências automaticamente na primeira execução."""
    flag_file = ".deps_installed.txt"
    if not os.path.exists(flag_file):
        with out:
            print("🆕 Primeira execução detectada! Verificando dependências...")
            try:
                # Força reload para garantir que estamos rodando a versão atualizada do disco
                importlib.reload(install_deps) 
                install_deps.install()
            except Exception as e:
                print(f"❌ Erro na instalação automática: {e}")
    else:
        pass

def display_ui():
    """Exibe a interface completa."""
    
    header = widgets.HTML("<h2>🎛️ BI Dashboard Interpreter - Painel de Controle</h2>")
    
    # Layout dos botões
    buttons_row1 = widgets.HBox([btn_save_simple, btn_report])
    buttons_row2 = widgets.HBox([btn_update, btn_reset])
    buttons_row3 = widgets.HBox([btn_run_batch, btn_run_seq]) # Execução
    
    # Monta UI
    ui = widgets.VBox([
        header, 
        widgets.HTML("<b>1. Defina as URLs para atualizar ou processar:</b>"),
        url_area,
        widgets.HTML("<br><b>2. Ações de Configuração:</b>"),
        buttons_row1,
        buttons_row2,
        widgets.HTML("<br><b>3. Logs de Configuração:</b>"),
        out,
        widgets.HTML("<br><b>4. Execução (Abre PowerShell):</b>"), # Separador visual claro
        buttons_row3,
        out_exec # Novo log dedicado logo abaixo dos botões de execução
    ])
    
    display(ui)
    
    # Check pós-renderização
    check_dependencies()
