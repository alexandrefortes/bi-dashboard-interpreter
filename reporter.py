import os
import json
import shutil
import glob
from pathlib import Path
from datetime import datetime

# Config
RUNS_DIR = "runs"
TEMPLATE_PATH = os.path.join("templates", "viewer_template.html")
REPORT_DIR = "bi_catalog_report"
IMAGES_DIR = "images"

def setup_report_dir():
    """Cria a estrutura de pastas do relatório, limpando se necessário (exceto imagens se quiser otimizar, mas vamos limpar para garantir consistência)."""
    report_path = Path(REPORT_DIR)
    images_path = report_path / IMAGES_DIR
    
    if report_path.exists():
        # Opção: Limpar tudo para garantir que não haja lixo de runs antigos
        # Se ficar muito lento com muitas imagens, podemos otimizar depois
        pass 
    else:
        report_path.mkdir(parents=True, exist_ok=True)
        
    if not images_path.exists():
        images_path.mkdir(parents=True, exist_ok=True)
        
    return report_path, images_path

def collect_data(report_images_path: Path):
    """Varre a pasta RUNS, coleta JSONs e copia imagens."""
    all_catalogs = []
    
    # Busca recursiva por arquivos de catálogo catalog_*.json
    # Padrão: runs/<run_id_folder>/catalog_*.json
    search_pattern = os.path.join(RUNS_DIR, "**", "catalog_*.json")
    json_files = glob.glob(search_pattern, recursive=True)
    
    print(f"> Encontrados {len(json_files)} arquivos de catalogo.")
    
    for json_file in json_files:
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            run_id = data.get('run_id', 'unknown')
            run_folder = os.path.dirname(json_file)
            
            # Processar páginas e imagens
            pages = data.get('pages', [])
            for page in pages:
                original_filename = page.get('filename')
                if original_filename:
                    # Caminho original da imagem: runs/<run_id>/screenshots/<filename>
                    # OU runs/<run_id>/<filename> (dependendo da versão do bot)
                    
                    # Tenta achar a imagem
                    possible_paths = [
                        os.path.join(run_folder, "screenshots", original_filename),
                        os.path.join(run_folder, original_filename)
                    ]
                    
                    src_image_path = None
                    for p in possible_paths:
                        if os.path.exists(p):
                            src_image_path = p
                            break
                    
                    if src_image_path:
                        # Para evitar conflito de nomes (01_home.png pode existir em vários runs),
                        # prefixamos com o run_id
                        new_filename = f"{run_id}_{original_filename}"
                        dest_image_path = report_images_path / new_filename
                        
                        # Copia a imagem
                        shutil.copy2(src_image_path, dest_image_path)
                        
                        # Atualiza o caminho no JSON para ser relativo ao HTML
                        # HTML está em bi_catalog_report/index.html
                        # Imagens estão em bi_catalog_report/images/
                        page['screenshot_rel_path'] = f"{IMAGES_DIR}/{new_filename}"
                    else:
                        print(f"! Imagem nao encontrada para {run_id}: {original_filename}")
                        page['screenshot_rel_path'] = "" # Placeholder ou vazio
            
            all_catalogs.append(data)
            
        except Exception as e:
            print(f"! Erro ao processar {json_file}: {e}")
            
    # Ordenar por data (mais recente primeiro)
    all_catalogs.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    return all_catalogs

def generate_report():
    print(">>> Iniciando geracao do relatorio estatico...")
    
    # 1. Setup pastas
    report_path, images_path = setup_report_dir()
    
    # 2. Coletar dados e copiar assets
    catalog_data = collect_data(images_path)
    
    if not catalog_data:
        print("!!! Nenhum dado encontrado. Verifique se ha execucoes na pasta runs.")
        return

    # 3. Ler template e injetar dados
    try:
        with open(TEMPLATE_PATH, 'r', encoding='utf-8') as f:
            template_content = f.read()
            
        # Serializa dados para JS
        json_str = json.dumps(catalog_data, ensure_ascii=False)
        
        # Injeção simples de string (pode melhorar com jinja2 se necessário, mas str.replace resolve)
        # O template deve ter: window.CATALOG_DATA = [];
        final_html = template_content.replace(
            "window.CATALOG_DATA = [];", 
            f"window.CATALOG_DATA = {json_str};"
        )
        
        # 4. Salvar index.html
        output_file = report_path / "index.html"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(final_html)
            
        print(f">>> Relatorio gerado com sucesso!")
        print(f">>> Local: {output_file.absolute()}")
        return str(output_file.absolute())

    except FileNotFoundError:
        print(f"!!! Erro: Template nao encontrado em {TEMPLATE_PATH}")

if __name__ == "__main__":
    generate_report()
