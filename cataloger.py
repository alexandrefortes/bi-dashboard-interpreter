import asyncio
import json
from pathlib import Path
from datetime import datetime

from config import OUTPUT_DIR, DUPLICATE_THRESHOLD, VIEWPORT, CLICK_ATTEMPT_OFFSETS
from utils import setup_logger, bytes_to_image, compute_phash, is_error_screen, parse_page_count
from bot_core import BrowserDriver
from llm_service import GeminiService
from click_strategy import ConcentricSearchClicker, DOMFallbackClicker

logger = setup_logger("Cataloger")

class DashboardCataloger:
    def __init__(self):
        self.driver = BrowserDriver()
        self.llm = GeminiService()
        self.seen_hashes = [] # Lista de hashes já vistos para deduplicação

    def _is_duplicate(self, current_phash):
        """Verifica se a página já foi catalogada."""
        for seen_hash in self.seen_hashes:
            if current_phash - seen_hash < DUPLICATE_THRESHOLD:
                return True
        return False

    async def process_dashboard(self, url):
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = Path(OUTPUT_DIR) / run_id
        img_dir = run_dir / "screenshots"
        img_dir.mkdir(parents=True, exist_ok=True)

        catalog_data = {
            "run_id": run_id,
            "url": url,
            "timestamp": datetime.now().isoformat(),
            "pages": []
        }

        try:
            # 1. Start & Navigate
            await self.driver.start(headless=False)
            success = await self.driver.navigate_and_stabilize(url)
            if not success:
                logger.error("Falha ao carregar dashboard.")
                return None

            # 2. Captura Inicial (com suporte a scroll para páginas longas)
            initial_bytes = await self.driver.get_full_page_screenshot_bytes()
            initial_pil = bytes_to_image(initial_bytes)
            
            if is_error_screen(initial_pil):
                logger.error("Tela de erro detectada. Abortando.")
                return None

            # Salva inicial
            (img_dir / "00_home.png").write_bytes(initial_bytes)
            
            # 3. Scout (Gemini identifica navegação)
            logger.info("Executando Scout (Gemini)...")
            nav_data = self.llm.discover_navigation(initial_bytes)
            
            # --- LÓGICA PARA EXPANDIR CLIQUES (Navegação Nativa) ---
            if nav_data.get("nav_type") == "native_footer" and nav_data.get("page_count_visual"):
                texto_paginas = nav_data["page_count_visual"]
                total_paginas = parse_page_count(texto_paginas)
                
                if total_paginas and total_paginas > 1 and nav_data.get("targets"):
                    paginas_restantes = total_paginas - 1
                    seta_next = nav_data["targets"][0]  # Assume que o único alvo é a seta
                    
                    novos_targets = []
                    for p in range(paginas_restantes):
                        alvo_clone = seta_next.copy()
                        alvo_clone['label'] = f"Ir para Pág {p+2}"
                        novos_targets.append(alvo_clone)
                    
                    nav_data["targets"] = novos_targets
                    logger.info(f"Expandindo navegação nativa para {len(novos_targets)} cliques.")
            # -----------------------------------------

            logger.info(f"Navegação detectada: {nav_data.get('nav_type')} | Alvos: {len(nav_data.get('targets', []))}")
            
            catalog_data["navigation_structure"] = nav_data
            
            # Prepara lista de ações (inclui a Home como primeira "ação" implícita)
            targets = nav_data.get("targets", [])
            
            # Adiciona a Home aos hashes vistos
            nav_type = nav_data.get("nav_type", "default")
            home_hash = compute_phash(initial_pil, nav_type)
            self.seen_hashes.append(home_hash)

            # Estrutura para fila de análise
            pages_to_analyze = [{
                "id": 0,
                "label": "Home",
                "bytes": initial_bytes,
                "hash": home_hash
            }]

            # Inicializa estratégias de clique
            clicker = ConcentricSearchClicker(self.driver, CLICK_ATTEMPT_OFFSETS, VIEWPORT)
            dom_fallback = DOMFallbackClicker(self.driver)

            # 4. Explorer (Itera sobre targets)
            for i, target in enumerate(targets):
                logger.info(f"--- Explorando alvo {i+1}/{len(targets)}: {target.get('label')} ---")

                # Tenta clique com estratégia Cross Search
                result = await clicker.click_with_retry(
                    target['x'], target['y'],
                    self.seen_hashes,
                    nav_type
                )
                
                # Se falhou e é navegação nativa, tenta fallback DOM
                if not result.success and nav_type == "native_footer":
                    result = await dom_fallback.try_dom_click(
                        self.seen_hashes,
                        nav_type
                    )
                
                # Se ainda falhou, desiste desse alvo
                if not result.success:
                    logger.error(f"💀 Alvo '{target.get('label')}' ignorado definitivamente.")
                    continue
                
                # SE CHEGOU AQUI, É UMA PÁGINA VÁLIDA NOVA
                self.seen_hashes.append(result.phash)
                
                # Salva imagem
                filename = f"{i+1:02d}_target.png"
                (img_dir / filename).write_bytes(result.screenshot_bytes)
                
                pages_to_analyze.append({
                    "id": i+1,
                    "label": target.get("label", f"Page {i+1}"),
                    "bytes": result.screenshot_bytes,
                    "filename": filename
                })

            # 5. Analyst (Analisa todas as páginas válidas coletadas)
            logger.info(f"Iniciando análise detalhada de {len(pages_to_analyze)} páginas...")
            
            for page in pages_to_analyze:
                logger.info(f"Analisando: {page['label']}")
                analysis = self.llm.analyze_page(page['bytes'])
                
                page_record = {
                    "id": page['id'],
                    "label": page['label'],
                    "filename": page.get('filename', '00_home.png'),
                    "analysis": analysis
                }
                catalog_data["pages"].append(page_record)

            # 6. Output Final
            json_path = run_dir / "catalog.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(catalog_data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Processo finalizado. Catálogo salvo em: {json_path}")
            return catalog_data

        finally:
            await self.driver.close()