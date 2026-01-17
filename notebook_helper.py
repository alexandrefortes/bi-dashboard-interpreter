import json
import shutil
import os
from pathlib import Path
import reporter

# Configurações de Caminhos
RUNS_DIR = Path("runs")
REPORT_DIR = Path("bi_catalog_report")
URLS_FILE = Path("urls.json")
PROCESSED_LOG = RUNS_DIR / "processed_urls.json"

def smart_update(urls_list):
    """
    Executa a lógica de 'Smart Update':
    1. Limpa histórico (pastas e JSON) para as URLs fornecidas.
    2. Reseta a pasta de relatório.
    3. Atualiza urls.json.
    """
    # Normaliza
    target_urls = set(u.strip() for u in urls_list if u.strip())
    
    if not target_urls:
        print("⚠️ Nenhuma URL válida fornecida.")
        return False

    cleaned_count = 0
    print(f"🔄 Iniciando Smart Update para {len(target_urls)} painéis...")

    # 1. Limpa do arquivo central de memória (processed_urls.json)
    if PROCESSED_LOG.exists():
        try:
            with open(PROCESSED_LOG, 'r', encoding='utf-8') as f:
                history = json.load(f)
            
            keys_to_remove = [url for url in history if url in target_urls]
            
            if keys_to_remove:
                for k in keys_to_remove:
                    del history[k]
                
                with open(PROCESSED_LOG, 'w', encoding='utf-8') as f:
                    json.dump(history, f, indent=2)
                print(f"🧠 Memória limpa: {len(keys_to_remove)} registros removidos.")
        except Exception as e:
            print(f"⚠️ Erro ao atualizar processed_urls.json: {e}")

    # 2. Limpa as pastas físicas
    if RUNS_DIR.exists():
        found_files = list(RUNS_DIR.glob("**/catalog_*.json"))
        for json_file in found_files:
            try:
                if not json_file.exists(): continue
                
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                saved_url = data.get('url', '').strip()
                if saved_url in target_urls:
                    folder_to_delete = json_file.parent
                    print(f"♻️  Deletando pasta antiga: {folder_to_delete.name}")
                    shutil.rmtree(folder_to_delete)
                    cleaned_count += 1
            except Exception as e:
                print(f"⚠️ Erro ao processar arquivo {json_file}: {e}")

    # 3. Reseta Interface Gráfica
    if REPORT_DIR.exists():
        try:
            shutil.rmtree(REPORT_DIR)
            print("✅ Interface Gráfica antiga removida.")
        except Exception as e:
            print(f"❌ Erro ao limpar report dir: {e}")

    # 4. Salva urls.json
    with open(URLS_FILE, "w", encoding="utf-8") as f:
        json.dump(list(target_urls), f, indent=2)

    print(f"📝 Arquivo 'urls.json' atualizado.")
    print(f"🚀 Tudo pronto! Execute: !python batch_main.py")
    return True

def reset_all():
    """Destrói todo o histórico e outputs."""
    folders = [RUNS_DIR, REPORT_DIR]
    print("☢️  Iniciando Reset Total...")
    
    for folder in folders:
        if folder.exists():
            try:
                shutil.rmtree(folder)
                print(f"✅ Deletado: {folder}")
            except Exception as e:
                print(f"❌ Erro ao deletar {folder}: {e}")
        else:
            print(f"ℹ️  Já não existia: {folder}")
            
    print("✨ Ambiente resetado com sucesso.")

def define_urls(urls_text):
    """Helper simples para salvar urls.json direto da caixa de texto."""
    urls = [line.strip() for line in urls_text.split('\n') if line.strip()]
    if urls:
        return smart_update(urls)
    else:
        print("⚠️ Caixa de texto vazia.")
        return False
