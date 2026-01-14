import asyncio
import json
import time
from pathlib import Path
from datetime import datetime

from config import OUTPUT_DIR, PHASH_THRESHOLD, DUPLICATE_THRESHOLD, VIEWPORT, CLICK_ATTEMPT_OFFSETS
from utils import setup_logger, bytes_to_image, compute_phash, is_error_screen
from bot_core import BrowserDriver
from llm_service import GeminiService

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

            # 2. Captura Inicial
            initial_bytes = await self.driver.get_screenshot_bytes()
            initial_pil = bytes_to_image(initial_bytes)
            
            if is_error_screen(initial_pil):
                logger.error("Tela de erro detectada. Abortando.")
                return None

            # Salva inicial
            (img_dir / "00_home.png").write_bytes(initial_bytes)
            
            # 3. Scout (Gemini identifica navegação)
            logger.info("Executando Scout (Gemini)...")
            nav_data = self.llm.discover_navigation(initial_bytes)
            
            # --- LÓGICA NOVA PARA EXPANDIR CLIQUES ---
            if nav_data.get("nav_type") == "native_footer" and nav_data.get("page_count_visual"):
                try:
                    # Tenta extrair "X de Y"
                    texto_paginas = nav_data["page_count_visual"] # ex: "1 de 4"
                    # Pega o último número da string (total de páginas)
                    import re
                    numeros = re.findall(r'\d+', texto_paginas)
                    if len(numeros) >= 2:
                        total_paginas = int(numeros[-1]) # Pega o 4
                        paginas_restantes = total_paginas - 1
                        
                        # Se tivermos um alvo de "próximo", multiplicamos ele
                        if nav_data.get("targets"):
                            seta_next = nav_data["targets"][0] # Assume que o unico alvo é a seta
                            novos_targets = []
                            for p in range(paginas_restantes):
                                # Cria uma cópia do alvo para cada página que falta
                                alvo_clone = seta_next.copy()
                                alvo_clone['label'] = f"Ir para Pág {p+2}"
                                novos_targets.append(alvo_clone)
                            
                            nav_data["targets"] = novos_targets
                            logger.info(f"Expandindo navegação nativa para {len(novos_targets)} cliques.")
                except Exception as e:
                    logger.warning(f"Erro ao calcular paginação nativa: {e}")
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

            # 4. Explorer (Itera sobre targets)
            for i, target in enumerate(targets):
                logger.info(f"--- Explorando alvo {i+1}/{len(targets)}: {target.get('label')} ---")

                # Reseta variáveis de controle               
                page_changed = False
                final_shot_bytes = None
                final_current_hash = None
                
                # --- LOOP DE TENTATIVA DE CLIQUE (Busca em Cruz) ---
                for attempt_idx, (off_x, off_y) in enumerate(CLICK_ATTEMPT_OFFSETS):
                    
                    # Converte offset de pixels para porcentagem
                    # (Precisamos disso pq o bot_core clica por %)
                    adj_x = target['x'] + (off_x / VIEWPORT['width'])
                    adj_y = target['y'] + (off_y / VIEWPORT['height'])
                    
                    if attempt_idx > 0:
                        logger.info(f"🔄 Tentativa {attempt_idx} (Offset {off_x}px, {off_y}px)...")
                    
                    # Clica
                    await self.driver.click_at_percentage(adj_x, adj_y)
                    
                    # Espera carregar (se for retry, espera menos pra ser ágil)
                    wait_time = 3 if attempt_idx == 0 else 2
                    await asyncio.sleep(wait_time)
                    
                    # Snapshot
                    shot_bytes = await self.driver.get_screenshot_bytes()
                    shot_pil = bytes_to_image(shot_bytes)
                    
                    if is_error_screen(shot_pil):
                        logger.warning("Tela de erro. Tentando próximo offset...")
                        continue

                    # Calcula Hash
                    current_hash = compute_phash(shot_pil, nav_type)
                    
                    # Verifica duplicata contra TUDO que já vimos
                    is_dup = False
                    for seen_hash in self.seen_hashes:
                        if current_hash - seen_hash < DUPLICATE_THRESHOLD:
                            is_dup = True
                            break
                    
                    if not is_dup:
                        # SUCESSO! A página mudou.
                        logger.info(f"✅ Clique funcionou (com offset {off_x},{off_y})!")
                        page_changed = True
                        final_shot_bytes = shot_bytes
                        final_current_hash = current_hash
                        break # Sai do loop de tentativas
                    else:
                        if attempt_idx == 0:
                            logger.warning("⚠️ Clique original não alterou a página. Iniciando busca em cruz...")
                
                # --- FIM DO LOOP DE CLIQUE ---

                # Se depois de todas as tentativas a página ainda for duplicada:
                if not page_changed:
                    logger.warning("🚫 Falha: Todas as tentativas de clique resultaram em página duplicada.")
                    
                    # --- TENTATIVA DE RESGATE (FALLBACK DOM) ---
                    # Mantive sua lógica original de resgate aqui como última esperança
                    if nav_type == "native_footer":
                        logger.info("🚑 Tentando resgate com clique nativo via DOM...")
                        clicked_dom = await self.driver.try_click_native_next_button()
                        if clicked_dom:
                            await asyncio.sleep(5)
                            shot_bytes = await self.driver.get_screenshot_bytes()
                            shot_pil = bytes_to_image(shot_bytes)
                            current_hash = compute_phash(shot_pil, nav_type)
                            
                            # Re-verifica duplicata do resgate
                            is_dup_retry = False
                            for seen_hash in self.seen_hashes:
                                if current_hash - seen_hash < DUPLICATE_THRESHOLD:
                                    is_dup_retry = True
                                    break
                            
                            if not is_dup_retry:
                                logger.info("✅ Resgate DOM funcionou!")
                                page_changed = True
                                final_shot_bytes = shot_bytes
                                final_current_hash = current_hash

                # Se ainda assim não mudou, desiste desse alvo e vai pro próximo
                if not page_changed:
                    logger.error(f"💀 Alvo '{target.get('label')}' ignorado definitivamente.")
                    continue
                
                # SE CHEGOU AQUI, É UMA PÁGINA VÁLIDA NOVA
                self.seen_hashes.append(final_current_hash)
                
                # Salva imagem
                filename = f"{i+1:02d}_target.png"
                (img_dir / filename).write_bytes(final_shot_bytes)
                
                pages_to_analyze.append({
                    "id": i+1,
                    "label": target.get("label", f"Page {i+1}"),
                    "bytes": final_shot_bytes,
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