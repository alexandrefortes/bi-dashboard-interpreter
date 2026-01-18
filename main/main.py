import asyncio
import sys
import json
import os
from datetime import datetime
from pathlib import Path

from config import OUTPUT_DIR
import reporter
from cataloger import DashboardCataloger
from utils import setup_logger
from bot_core import BrowserDriver

# Nome do arquivo temporário de troca de dados
CONFIG_FILE = "urls.json"
logger = setup_logger("Main")

def load_urls():
    """Carrega URLs do arquivo JSON"""
    urls = []

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                urls = json.load(f)
                if isinstance(urls, list):
                    return urls
        except Exception as e:
            print(f"⚠️ Erro ao ler {CONFIG_FILE}: {e}")

    # Fallback: Lista vazia (retornará erro amigável)
    return []

async def main():
    urls_para_processar = load_urls()
    
    # Deduplicação (mantendo ordem)
    seen = set()
    unique_urls = []
    for u in urls_para_processar:
        if u not in seen:
            unique_urls.append(u)
            seen.add(u)
    urls = unique_urls

    if not urls:
        print("❌ Nenhuma URL encontrada!")
        print(f"   Certifique-se de que o notebook criou o arquivo '{CONFIG_FILE}'")
        return

    print(f"📋 Encontradas {len(urls)} URLs para processar.")
    
    # --- MODO PERSISTENTE (Browser compartilhado) ---
    logger.info("🚀 Iniciando navegador mestre (Sessão Persistente)...")
    persistent_driver = BrowserDriver()
    await persistent_driver.start(headless=False) # Abre navegador UMA vez
    
    reports = []
    
    try:
        for i, url in enumerate(urls):
            print(f"\n🔹 Processando {i+1}/{len(urls)}: {url}")
            
            # Passa o driver já aberto para o Cataloger
            cataloger = DashboardCataloger(driver=persistent_driver)
            
            try:
                result = await cataloger.process_dashboard(url)
                if result:
                    reports.append(result)
                    print(f"   ✅ Sucesso: {url}")
                else:
                    print(f"   ⚠️ Ignorado/Erro: {url}")
            except Exception as e:
                logger.error(f"Erro ao processar {url}: {e}")
                print(f"   ❌ Erro crítico no item {i+1}")
                # Não aborta o loop, tenta o próximo
                
    except KeyboardInterrupt:
        print("\n🛑 Interrompido pelo usuário.")
        
    finally:
        # ATENÇÃO: Mantendo navegador aberto conforme solicitado pelo usuário
        print("\n🏁 Processamento em lote finalizado.")
        print("🌍 O navegador permanecerá ABERTO para preservar a sessão/login.")
        print("⚠️ Para fechar, feche a janela manualmente ou pare o kernel.")
        
        # Gera relatório final
        if reports:
            try:
                report_path = Path(OUTPUT_DIR) / f"batch_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                with open(report_path, "w", encoding="utf-8") as f:
                    json.dump(reports, f, indent=2, ensure_ascii=False)
                print(f"\n📄 Relatório consolidado salvo em: {report_path}")
                
                # Gera HTML também
                reporter.generate_report()
            except Exception as e:
                print(f"Erro ao gerar relatorio final: {e}")

if __name__ == "__main__":
    try:
        if sys.platform == 'win32':
             asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProcesso interrompido pelo usuário.")