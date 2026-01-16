import asyncio
import json
from pathlib import Path
from datetime import datetime

from config import OUTPUT_DIR
from utils import setup_logger, bytes_to_image, compute_phash, is_error_screen, parse_page_count, sanitize_filename
from bot_core import BrowserDriver
from llm_service import GeminiService
from explorer import DashboardExplorer

logger = setup_logger("Cataloger")

class DashboardCataloger:
    def __init__(self):
        self.driver = BrowserDriver()
        self.llm = GeminiService()
        self.processed_urls_file = Path(OUTPUT_DIR) / "processed_urls.json"
        
    def _load_processed_urls(self):
        """Carrega lista de URLs já processadas."""
        if self.processed_urls_file.exists():
            try:
                with open(self.processed_urls_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Erro ao carregar processed_urls.json: {e}")
                return {}
        return {}

    def _mark_as_processed(self, url, run_id, log_path):
        """Marca URL como processada."""
        data = self._load_processed_urls()
        data[url] = {
            "processed_at": datetime.now().isoformat(),
            "run_id": run_id,
            "log_path": str(log_path)
        }
        try:
            with open(self.processed_urls_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Erro ao salvar processed_urls.json: {e}")

    async def process_dashboard(self, url):
        # 0. Verifica Deduplicação
        processed = self._load_processed_urls()
        if url in processed:
            last_run = processed[url]
            logger.warning(f"⏭️ URL já processada em {last_run.get('processed_at')} (Run: {last_run.get('run_id')}). Pulando.")
            return None

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
            
            # --- SALVA AUDITORIA SCOUT ---
            if "raw_response" in nav_data:
                audit_path = run_dir / "scout_audit_raw.txt"
                try:
                    audit_path.write_text(nav_data["raw_response"] or "", encoding="utf-8")
                    # Remove do dicionário principal para não sujar o catalog.json
                    del nav_data["raw_response"]
                except Exception as e:
                    logger.warning(f"Falha ao salvar auditoria Scout: {e}")
            # -----------------------------
            
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
            
            # 4. Explorer (Delega para classe especializada)
            explorer = DashboardExplorer(self.driver, run_dir)
            
            # Executa exploração
            new_pages = await explorer.explore(targets, nav_type, home_hash)
            
            # Monta lista final para análise (Home + Novas Páginas)
            pages_to_analyze = [{
                "id": 0,
                "label": "Home",
                "bytes": initial_bytes,
                "hash": home_hash,
                "filename": "00_home.png"
            }] + new_pages

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

            # 6. Output Final - Com título no nome da pasta e arquivo
            titulo_painel = ""
            if catalog_data["pages"]:
                titulo_painel = catalog_data["pages"][0].get("analysis", {}).get("titulo_painel", "")
            
            titulo_safe = sanitize_filename(titulo_painel)
            
            # Renomeia a pasta para incluir o título
            if titulo_safe:
                new_run_dir = Path(OUTPUT_DIR) / f"{run_id}_{titulo_safe}"
                try:
                    run_dir.rename(new_run_dir)
                    run_dir = new_run_dir
                    logger.info(f"Pasta renomeada para: {run_dir.name}")
                except Exception as e:
                    logger.warning(f"Não foi possível renomear pasta: {e}")
            
            # Nome do catalog.json com título
            catalog_filename = f"catalog_{titulo_safe}.json" if titulo_safe else "catalog.json"
            json_path = run_dir / catalog_filename
            
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(catalog_data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Processo finalizado. Catálogo salvo em: {json_path}")
            
            # 7. Marca como processado com sucesso
            self._mark_as_processed(url, run_id, json_path)
            
            return catalog_data

        finally:
            await self.driver.close()