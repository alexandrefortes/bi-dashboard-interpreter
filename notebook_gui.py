import ipywidgets as widgets
from IPython.display import display, clear_output, HTML
import notebook_helper
import reporter
import install_deps
import sys
import io
import os
import webbrowser

# Widget de Saída Global (para capturar prints)
out = widgets.Output(layout={'border': '1px solid #ddd', 'height': '300px', 'overflow_y': 'scroll'})

def capture_output(func):
    """Decorator para capturar stdout/stderr dentro do widget."""
    def wrapper(*args, **kwargs):
        with out:
            # Limpa output anterior para manter a interface limpa
            clear_output(wait=True) 
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
        print("\n📜 [Backup] Conteúdo anterior de urls.json (salvo em urls_old.json):")
        print(old_urls)

@capture_output
def on_click_save_simple(b):
    urls = url_area.value
    if not urls.strip():
        print("⚠️ Por favor, insira pelo menos uma URL.")
        return

    print("\n--- 💾 Salvar URLs (Sem Limpeza) ---")
    notebook_helper.define_urls(urls, mode="simple")

@capture_output
def on_click_reset(b):
    print("\n--- ☢️ Reset Total ---")
    notebook_helper.reset_all()

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

# Layout comum para botões (para ficarem largos e legíveis)
btn_layout = widgets.Layout(width='48%')

# Botões
btn_update = widgets.Button(
    description='Atualizar (Smart Update)',
    button_style='primary', 
    icon='check',
    tooltip='Limpa histórico dessas URLs e atualiza lista',
    layout=btn_layout
)
btn_update.on_click(on_click_update)

btn_save_simple = widgets.Button(
    description='Processar/Continuar (Novo Lote)',
    button_style='success',
    icon='save',
    tooltip='Apenas salva lista para processamento (não deleta nada)',
    layout=btn_layout
)
btn_save_simple.on_click(on_click_save_simple)

btn_reset = widgets.Button(
    description='Reset de Fábrica (Apagar Tudo)',
    button_style='danger',
    icon='trash',
    layout=btn_layout
)
btn_reset.on_click(on_click_reset)

btn_report = widgets.Button(
    description='Gerar/Ver Relatório',
    button_style='info',
    icon='table',
    layout=btn_layout
)
btn_report.on_click(on_click_report)

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
    
    # Monta UI
    ui = widgets.VBox([
        header, 
        widgets.HTML("<b>1. Defina as URLs para atualizar ou processar:</b>"),
        url_area,
        widgets.HTML("<br><b>2. Ações:</b>"),
        buttons_row1,
        buttons_row2,
        widgets.HTML("<br><b>3. Logs de Execução:</b>"),
        out
    ])
    
    display(ui)
    
    # Check pós-renderização
    check_dependencies()
