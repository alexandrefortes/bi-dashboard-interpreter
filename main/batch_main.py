import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any
from playwright.async_api import async_playwright

import reporter
from cataloger import DashboardCataloger
from utils import setup_logger, current_worker_id

from config import MAX_CONCURRENT_TASKS, VIEWPORT

logger = setup_logger("BatchManager")

# Configurações do Batch
URLS_FILE = "urls.json"

async def process_single_url(url: str, semaphore: asyncio.Semaphore, shared_context: Any, file_lock: asyncio.Lock, worker_idx: int):
    """
    Worker que processa uma única URL respeitando o semáforo.
    Usa shared_context para manter sessão de login única.
    """
    # Define contexto para logs deste worker
    token = current_worker_id.set(f"Worker-{worker_idx}")
    
    async with semaphore:
        logger.info(f"🚦 [START] Iniciando worker para: {url}")
        try:
            # Passa o CONTEXTO compartilhado, não apenas o browser
            cataloger = DashboardCataloger(shared_context=shared_context, file_lock=file_lock)
            await cataloger.process_dashboard(url)
            logger.info(f"🏁 [DONE] Finalizado com sucesso: {url}")
        except Exception as e:
            logger.error(f"❌ [ERROR] Falha no worker ({url}): {e}")
            
    # Opcional em async, mas boa prática limpar
    current_worker_id.reset(token)

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
        
        # Opcional: Pré-filtro de URLs já processadas
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
    logger.info("🚀 Iniciando Motor Batch (Modo Persistente)...")
    
    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-infobars"
    ]

    async with async_playwright() as p:
        # Tenta usar Chrome do Sistema (Stealth Mode)
        try:
            browser = await p.chromium.launch(
                headless=False,
                channel="chrome", 
                args=launch_args,
                ignore_default_args=["--enable-automation"]
            )
            logger.info("✅ Google Chrome (System) iniciado para Batch.")
        except Exception as e:
             logger.warning(f"⚠️ Falha Chrome System ({e}). Usando Chromium bundled.")
             browser = await p.chromium.launch(headless=False, args=launch_args)

        # 4. CRIA CONTEXTO MESTRE (onde o login vai viver)
        # Todos os workers vão criar abas (pages) dentro deste contexto
        context = await browser.new_context(
            viewport=VIEWPORT,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        logger.info("🍪 Contexto Mestre criado. Faça login agora (se necessário) na primeira aba que abrir!")
        
        try:
            # 5. Cria e agenda tarefas
            tasks = []
            for i, url in enumerate(urls):
                task = asyncio.create_task(
                    process_single_url(url, semaphore, context, file_lock, i+1)
                )
                tasks.append(task)
            
            # 6. Aguarda conclusão
            logger.info("⏳ Aguardando conclusão dos workers...")
            await asyncio.gather(*tasks)
            
        except KeyboardInterrupt:
            logger.warning("🛑 Interrompido pelo usuário.")
        except Exception as e:
            logger.error(f"❌ Erro no processamento em lote: {e}")
        
        # ATENÇÃO: NÃO fechamos navegador para preservar sessão/login
        logger.info("\n🏁 Processamento em lote finalizado.")
        logger.info("🌍 O navegador permanecerá ABERTO para preservar a sessão/login.")
        logger.info("⚠️ Para fechar, feche a janela manualmente ou pare o kernel.")
        
        # Gera relatório estático final
        try:
            reporter.generate_report()
        except Exception as e:
            logger.error(f"Erro ao gerar relatorio final: {e}")
        
        # Mantém o script rodando para não derrubar o navegador
        logger.info("💤 Aguardando... (Ctrl+C para sair)")
        try:
            while True:
                await asyncio.sleep(60)
        except KeyboardInterrupt:
            logger.info("👋 Encerrando...")
            await context.close()
            await browser.close()

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        
    asyncio.run(main())
