import asyncio
import json
import logging
from pathlib import Path
from playwright.async_api import async_playwright

from cataloger import DashboardCataloger
from utils import setup_logger

logger = setup_logger("BatchManager")

# Configurações do Batch
MAX_CONCURRENT_TASKS = 3  # Ajuste conforme memória disponível (3 = ~3GB RAM)
URLS_FILE = "urls.json"

async def process_single_url(url: str, semaphore: asyncio.Semaphore, browser_instance, file_lock: asyncio.Lock):
    """
    Worker que processa uma única URL respeitando o semáforo.
    """
    async with semaphore:
        logger.info(f"🚦 [START] Iniciando worker para: {url}")
        try:
            cataloger = DashboardCataloger(shared_browser=browser_instance, file_lock=file_lock)
            await cataloger.process_dashboard(url)
            logger.info(f"🏁 [DONE] Finalizado com sucesso: {url}")
        except Exception as e:
            logger.error(f"❌ [ERROR] Falha no worker ({url}): {e}")

async def main():
    # 1. Carrega URLs
    try:
        urls_path = Path(URLS_FILE)
        if not urls_path.exists():
            logger.error(f"Arquivo {URLS_FILE} não encontrado!")
            return
            
        urls = json.loads(urls_path.read_text(encoding='utf-8'))
        # Filtra strings vazias
        urls = [u for u in urls if u and u.strip()]
        
        # Deduplicação (mantendo ordem)
        seen = set()
        unique_urls = []
        for u in urls:
            if u not in seen:
                unique_urls.append(u)
                seen.add(u)
        
        # Opcional: Pré-filtro de URLs já processadas para evitar overhead de task
        try:
             processed_path = Path("runs/processed_urls.json")
             if processed_path.exists():
                 processed_data = json.loads(processed_path.read_text(encoding='utf-8'))
                 unique_urls = [u for u in unique_urls if u not in processed_data]
                 if len(urls) != len(unique_urls):
                     logger.info(f"ℹ️ {len(urls) - len(unique_urls)} URLs já processadas foram removidas da lista.")
        except Exception as e:
            logger.warning(f"Erro ao verificar processed_urls.json no batch: {e}")

        urls = unique_urls
        logger.info(f"Fila Final: {len(urls)} URLs únicas para processamento.")
    except Exception as e:
        logger.error(f"Erro ao ler urls.json: {e}")
        return

    # 2. Setup de Concorrência
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_TASKS)
    file_lock = asyncio.Lock()
    
    # 3. Inicia Navegador Compartilhado (Mãe)
    logger.info("🚀 Iniciando Motor Batch (Chromium Compartilhado)...")
    async with async_playwright() as p:
        # Lança navegador UMA vez
        browser = await p.chromium.launch(headless=False)
        
        try:
            # 4. Cria e agenda tarefas
            tasks = []
            for url in urls:
                task = asyncio.create_task(
                    process_single_url(url, semaphore, browser, file_lock)
                )
                tasks.append(task)
            
            # 5. Aguarda conclusão
            logger.info("⏳ Aguardando conclusão dos workers...")
            await asyncio.gather(*tasks)
            
        finally:
            logger.info("🛑 Fechando navegador compartilhado...")
            await browser.close()

    logger.info("✨ Processamento em Lote Finalizado! ✨")

if __name__ == "__main__":
    # Windows Selector Event Loop Policy fix
    import sys
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    asyncio.run(main())
