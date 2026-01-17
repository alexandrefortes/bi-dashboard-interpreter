import ipywidgets as widgets
from IPython.display import display, clear_output, HTML
import notebook_helper
import reporter
import install_deps
import sys
import io
import os

# Widget de Saída Global (para capturar prints)
out = widgets.Output(layout={'border': '1px solid #ddd', 'height': '300px', 'overflow_y': 'scroll'})

def capture_output(func):
    """Decorator para capturar stdout/stderr dentro do widget."""
    def wrapper(*args, **kwargs):
        with out:
            # Limpa output anterior se quiser algo mais limpo, ou mantém histórico
            # clear_output() 
            try:
                func(*args, **kwargs)
            except Exception as e:
                print(f"❌ Erro: {e}")
    return wrapper

# --- Botões e Ações ---

url_area = widgets.Textarea(
    value='',
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
    
    print("\n--- 🔄 Atualizar Painéis ---")
    notebook_helper.define_urls(urls)

@capture_output
def on_click_reset(b):
    print("\n--- ☢️ Reset Total ---")
    notebook_helper.reset_all()

@capture_output
def on_click_report(b):
    print("\n--- 📊 Gerar Relatório ---")
    path = reporter.generate_report()
    if path:
        display(HTML(f"👉 <a href='bi_catalog_report/index.html' target='_blank'>Abrir Relatório</a>"))

# Botões
btn_update = widgets.Button(
    description='Atualizar (Smart Update)',
    button_style='primary', # 'success', 'info', 'warning', 'danger' or ''
    icon='check'
)
btn_update.on_click(on_click_update)

btn_reset = widgets.Button(
    description='Reset de Fábrica (Apagar Tudo)',
    button_style='danger',
    icon='trash'
)
btn_reset.on_click(on_click_reset)

btn_report = widgets.Button(
    description='Gerar/Ver Relatório',
    button_style='info',
    icon='table'
)
btn_report.on_click(on_click_report)

def check_dependencies():
    """Verifica e instala dependências automaticamente na primeira execução."""
    flag_file = ".deps_installed.txt"
    if not os.path.exists(flag_file):
        with out:
            print("🆕 Primeira execução detectada! Verificando dependências...")
            try:
                install_deps.install()
            except Exception as e:
                print(f"❌ Erro na instalação automática: {e}")
    else:
        # Opcional: Avisar que já está tudo ok ou ficar silente
        # with out:
        #     print("✅ Ambiente verificado.")
        pass

def display_ui():
    """Exibe a interface completa."""
    
    header = widgets.HTML("<h2>🎛️ BI Dashboard Interpreter - Painel de Controle</h2>")
    
    # Layout dos botões
    buttons = widgets.HBox([btn_update, btn_report, btn_reset])
    
    # Monta UI
    ui = widgets.VBox([
        header, 
        widgets.HTML("<b>1. Defina as URLs para atualizar ou processar:</b>"),
        url_area,
        widgets.HTML("<br><b>2. Ações:</b>"),
        buttons,
        widgets.HTML("<br><b>3. Logs de Execução:</b>"),
        out
    ])
    
    display(ui)
    
    # Check pós-renderização
    check_dependencies()
