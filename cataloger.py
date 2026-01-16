import hashlib
import json
import shutil
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
        # 0. Verifica Deduplicação (Histórico de Sucesso)
        processed = self._load_processed_urls()
        if url in processed:
            last_run = processed[url]
            logger.warning(f"⏭️ URL já processada em {last_run.get('processed_at')} (Run: {last_run.get('run_id')}). Pulando.")
            return None

        # 1. Definição do Diretório de Trabalho (WIP - Work In Progress)
        # Usamos um hash da URL para criar uma pasta de trabalho persistente entre execuções
        url_hash = hashlib.md5(url.encode('utf-8')).hexdigest()
        wip_dir = Path(OUTPUT_DIR) / f"wip_{url_hash}"
        wip_dir.mkdir(parents=True, exist_ok=True)
        
        img_dir = wip_dir / "screenshots"
        img_dir.mkdir(parents=True, exist_ok=True)

        # Arquivos de Checkpoint
        scout_checkpoint = wip_dir / "scout_checkpoint.json"
        explore_checkpoint = wip_dir / "exploration_checkpoint.json"

        # Variáveis de Estado
        initial_bytes = None
        initial_pil = None
        nav_data = None
        pages_to_analyze = []
        
        try:
            # --- FASE 1: SCOUT (Batedor) ---
            # Verifica se já temos o resultado do Scout
            if scout_checkpoint.exists():
                logger.info("💾 Checkpoint do Scout encontrado. Carregando...")
                try:
                    nav_data = json.loads(scout_checkpoint.read_text(encoding='utf-8'))
                    run_id = nav_data.get("_meta_run_id", datetime.now().strftime("%Y%m%d_%H%M%S"))
                    
                    # Tenta carregar imagem inicial se existir
                    if (img_dir / "00_home.png").exists():
                        initial_bytes = (img_dir / "00_home.png").read_bytes()
                        initial_pil = bytes_to_image(initial_bytes)
                except Exception as e:
                    logger.warning(f"Erro ao ler checkpoint do Scout: {e}. Reiniciando fase.")
            
            # Se não recuperou nav_data, roda o fluxo normal
            if not nav_data:
                logger.info("Iniciando navegação (Browser)...")
                await self.driver.start(headless=False)
                success = await self.driver.navigate_and_stabilize(url)
                if not success:
                    logger.error("Falha ao carregar dashboard.")
                    return None

                initial_bytes = await self.driver.get_full_page_screenshot_bytes()
                initial_pil = bytes_to_image(initial_bytes)
                
                if is_error_screen(initial_pil):
                    logger.error("Tela de erro detectada. Abortando.")
                    return None
                    
                (img_dir / "00_home.png").write_bytes(initial_bytes)
                
                logger.info("Executando Scout (Gemini)...")
                nav_data = self.llm.discover_navigation(initial_bytes)
                
                # Salva Checkpoint Scout
                nav_data["_meta_run_id"] = datetime.now().strftime("%Y%m%d_%H%M%S") # Guarda ID original
                scout_checkpoint.write_text(json.dumps(nav_data, indent=2), encoding='utf-8')
                
                # Salva Auditoria Raw (mantendo compatibilidade)
                if "raw_response" in nav_data:
                    (wip_dir / "scout_audit_raw.txt").write_text(nav_data["raw_response"] or "", encoding="utf-8")
                    del nav_data["raw_response"]


            # --- FASE 2: EXPLORER (Explorador) ---
            if explore_checkpoint.exists():
                logger.info("💾 Checkpoint de Exploração encontrado. Carregando páginas...")
                try:
                    pages_to_analyze = json.loads(explore_checkpoint.read_text(encoding='utf-8'))
                    # Precisamos garantir que os bytes das imagens estejam em memória para o Analyst
                    # O JSON tem 'filename', vamos reler do disco
                    valid_pages = []
                    for page in pages_to_analyze:
                        p_file = img_dir / page.get("filename", "")
                        if p_file.exists():
                            page['bytes'] = p_file.read_bytes() # Recarrega bytes
                            valid_pages.append(page)
                        else:
                            logger.warning(f"Imagem {page.get('filename')} não encontrada. Ignorando página.")
                    pages_to_analyze = valid_pages
                    
                except Exception as e:
                    logger.warning(f"Erro ao ler checkpoint de Exploração: {e}. Reiniciando fase.")
                    pages_to_analyze = []

            # Se não recuperou páginas, roda o Explorer
            if not pages_to_analyze:
                # Garante driver aberto se não veio do fluxo anterior (ex: crashou após Scout)
                if not self.driver.page: 
                     await self.driver.start(headless=False)
                     # Precisamos re-navegar se o driver reiniciou? 
                     # Se já passamos do Scout, teoricamente sim, mas o Explorer precisa estar na página?
                     # O Explorer clica. Então SIM, precisa estar na página inicial.
                     # Mas se já temos nav_data, podemos tentar ir direto? 
                     # Melhor garantir estabilidade:
                     await self.driver.navigate_and_stabilize(url) 

                targets = nav_data.get("targets", [])
                
                # Prepara Home
                nav_type = nav_data.get("nav_type", "default")
                home_hash = compute_phash(initial_pil, nav_type) if initial_pil else "init"
                
                explorer = DashboardExplorer(self.driver, wip_dir)
                new_pages = await explorer.explore(targets, nav_type, home_hash)
                
                # Monta lista
                # Nota: Recarrega home bytes se necessário (caso tenha vindo de checkpoint scout)
                if not initial_bytes and (img_dir / "00_home.png").exists():
                     initial_bytes = (img_dir / "00_home.png").read_bytes()

                pages_to_analyze = [{
                    "id": 0,
                    "label": "Home",
                    "bytes": initial_bytes,
                    "filename": "00_home.png"
                }] + new_pages
                
                # Salva Checkpoint Explorer
                # Remove bytes antes de salvar JSON
                pages_serializable = []
                for p in pages_to_analyze:
                    p_copy = p.copy()
                    if 'bytes' in p_copy: del p_copy['bytes'] # Não serializa bytes
                    pages_serializable.append(p_copy)
                
                explore_checkpoint.write_text(json.dumps(pages_serializable, indent=2), encoding='utf-8')

            
            # --- FASE 3: ANALYST (Analista) ---
            # Pode rodar sem browser se tivermos as imagens carregadas
            if self.driver.page: 
                await self.driver.close() # Libera recurso antes da análise pesada
            
            logger.info(f"Iniciando análise detalhada de {len(pages_to_analyze)} páginas...")
            
            catalog_pages = []
            for page in pages_to_analyze:
                logger.info(f"Analisando: {page['label']}")
                
                # Se faltar bytes (recuperação falhou?), tenta ler
                if 'bytes' not in page or not page['bytes']:
                     p_file = img_dir / page.get("filename", "")
                     if p_file.exists():
                         page['bytes'] = p_file.read_bytes()
                
                if 'bytes' in page and page['bytes']:
                    analysis = self.llm.analyze_page(page['bytes'])
                    page_record = {
                        "id": page['id'],
                        "label": page['label'],
                        "filename": page.get('filename', '00_home.png'),
                        "analysis": analysis
                    }
                    catalog_pages.append(page_record)
                else:
                    logger.error(f"Sem imagem para analisar página {page['label']}")


            # --- FINALIZAÇÃO E ARQUIVAMENTO ---
            # Gera nome final
            run_id = datetime.now().strftime("%Y%m%d_%H%M%S") # ID da finalização
            
            titulo_painel = ""
            if catalog_pages:
                titulo_painel = catalog_pages[0].get("analysis", {}).get("titulo_painel", "")
            
            titulo_safe = sanitize_filename(titulo_painel)
            final_folder_name = f"{run_id}_{titulo_safe}" if titulo_safe else run_id
            final_run_dir = Path(OUTPUT_DIR) / final_folder_name
            
            catalog_data = {
                "run_id": run_id,
                "url": url,
                "timestamp": datetime.now().isoformat(),
                "navigation_structure": nav_data,
                "pages": catalog_pages
            }

            # Renomeia pasta WIP para Final
            try:
                # Primeiro salva o catálago dentro da WIP
                catalog_filename = f"catalog_{titulo_safe}.json" if titulo_safe else "catalog.json"
                json_path = wip_dir / catalog_filename
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(catalog_data, f, indent=2, ensure_ascii=False)
                
                # Checkpoints não são mais necessários na pasta final? 
                # Pode apagar ou deixar. Vamos deixar como log.
                
                wip_dir.rename(final_run_dir)
                logger.info(f"Pasta finalizada e renomeada para: {final_run_dir.name}")
                
                 # Caminho atualizado do json
                final_json_path = final_run_dir / catalog_filename
                self._mark_as_processed(url, run_id, final_json_path)
                
                return catalog_data

            except Exception as e:
                logger.error(f"Erro na finalização/renomeação: {e}")
                return catalog_data # Retorna o que tem

        except Exception as e:
            logger.error(f"Erro crítico no processamento: {e}")
            raise # Propaga para ver o erro no console
        finally:
            await self.driver.close()