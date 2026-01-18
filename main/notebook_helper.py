import json
import shutil
import os
from pathlib import Path
import reporter

from datetime import datetime

# Configurações de Caminhos
RUNS_DIR = Path("runs")
REPORT_DIR = Path("bi_catalog_report")
URLS_FILE = Path("urls.json")
BACKUP_DIR = Path("urls_json_backups")
PROCESSED_LOG = RUNS_DIR / "processed_urls.json"

def load_urls():
    """Carrega as URLs atuais do arquivo json (para preencher a interface)."""
    if URLS_FILE.exists():
        try:
            with open(URLS_FILE, 'r', encoding='utf-8') as f:
                urls = json.load(f)
            return "\n".join(urls)
        except:
            return ""
    return ""

def _backup_and_save_urls(target_urls):
    """Lógica interna: Faz backup do urls.json atual e salva o novo."""
    # 1. Backup com Timestamp
    if URLS_FILE.exists():
        try:
            BACKUP_DIR.mkdir(exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = BACKUP_DIR / f"urls_old_{timestamp}.json"
            
            shutil.copy2(URLS_FILE, backup_file)
            print(f"💾 Backup salvo em: {backup_file}")
        except Exception as e:
            print(f"⚠️ Falha no backup: {e}")
            
    # 2. Salvar Novo
    with open(URLS_FILE, "w", encoding="utf-8") as f:
        json.dump(list(target_urls), f, indent=2)
    print(f"📝 Arquivo 'urls.json' atualizado com {len(target_urls)} URLs.")

def get_old_urls_content():
    """Lê o conteúdo do backup mais recente para exibição."""
    if not BACKUP_DIR.exists():
        return None
        
    try:
        # Pega todos os backups
        files = list(BACKUP_DIR.glob("urls_old_*.json"))
        if not files:
            return None
            
        # Pega o mais recente baseado na data de criação
        latest_file = max(files, key=os.path.getctime)
        return latest_file.read_text(encoding='utf-8')
    except:
        return None

def smart_update(urls_list):
    """
    Executa a lógica de 'Smart Update':
    1. Limpa histórico (pastas e JSON) para as URLs fornecidas.
    2. Reseta a pasta de relatório.
    3. Atualiza urls.json (com backup).
    """
    target_urls = set(u.strip() for u in urls_list if u.strip())
    
    if not target_urls:
        print("⚠️ Nenhuma URL válida fornecida.")
        return False

    cleaned_count = 0
    print(f"🔄 Iniciando Smart Update para {len(target_urls)} painéis...")

    # 1. Limpa Memory (processed_urls.json)
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

    # 2. Limpa Pastas Físicas
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

    # 3. Reseta Interface
    if REPORT_DIR.exists():
        try:
            shutil.rmtree(REPORT_DIR)
            print("✅ Interface Gráfica antiga removida.")
        except Exception as e:
            print(f"❌ Erro ao limpar report dir: {e}")

    # 4. Salva urls.json (com Backup)
    _backup_and_save_urls(target_urls)

    return True

def save_urls_simple(urls_list):
    """
    Apenas atualiza o urls.json (com backup), SEM deletar runs antigos.
    Use para adicionar novos painéis ou reprocessar sem limpar histórico.
    """
    target_urls = set(u.strip() for u in urls_list if u.strip())
    
    if not target_urls:
        print("⚠️ Nenhuma URL válida fornecida.")
        return False
        
    print(f"💾 Salvando {len(target_urls)} URLs para processamento (Sem Limpeza)...")
    _backup_and_save_urls(target_urls)
    return True

def define_urls(urls_text, mode="smart"):
    """
    Helper principal.
    mode="smart" -> Smart Update (Limpa histórico)
    mode="simple" -> Apenas Salva (Mantém histórico)
    """
    urls = [line.strip() for line in urls_text.split('\n') if line.strip()]
    
    if mode == "smart":
        return smart_update(urls)
    elif mode == "simple":
        return save_urls_simple(urls)
    else:
        print("Modo inválido")
        return False

def reset_all():
    """
    Reset de Fábrica: Apaga TUDO para começar do zero.
    - Pasta de Logs (Runs)
    - Pasta de Relatórios
    - Arquivo de URLs
    - Backups
    """
    print("☢️ Iniciando Protocolo de Reset Total...")

    # 1. Runs
    if RUNS_DIR.exists():
        try:
            shutil.rmtree(RUNS_DIR)
            print("✅ Histórico de execuções (runs/) apagado.")
        except Exception as e:
            print(f"❌ Erro ao apagar runs: {e}")
    
    # 2. Relatórios
    if REPORT_DIR.exists():
        try:
            shutil.rmtree(REPORT_DIR)
            print("✅ Relatórios gerados (bi_catalog_report/) apagados.")
        except Exception as e:
            print(f"❌ Erro ao apagar relatórios: {e}")

    # 3. URLs
    if URLS_FILE.exists():
        try:
            os.remove(URLS_FILE)
            print("✅ Arquivo de URLs (urls.json) removido.")
        except Exception as e:
            print(f"❌ Erro ao apagar urls.json: {e}")
            
    # 4. Backups
    if BACKUP_DIR.exists():
        try:
            shutil.rmtree(BACKUP_DIR)
            print("✅ Pasta de Backups (urls_json_backups/) removida.")
        except Exception as e:
            print(f"❌ Erro ao apagar backups: {e}")
            
    print("✨ Sistema limpo e pronto para nova configuração.")
    return True
