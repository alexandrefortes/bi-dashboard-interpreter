import asyncio
from typing import List, Dict, Any, Optional
from pathlib import Path

from config import VIEWPORT, CLICK_ATTEMPT_OFFSETS
from utils import setup_logger, bytes_to_image, compute_phash
from click_strategy import ConcentricSearchClicker, DOMFallbackClicker

logger = setup_logger("Explorer")

class DashboardExplorer:
    """
    Responsável pela fase de exploração: clicar em alvos e coletar novas páginas.
    """
    def __init__(self, driver: Any, output_dir: Path):
        self.driver = driver
        self.img_dir = output_dir / "screenshots"
        self.img_dir.mkdir(parents=True, exist_ok=True)
        
        # Inicializa estratégias
        self.clicker = ConcentricSearchClicker(driver, CLICK_ATTEMPT_OFFSETS, VIEWPORT)
        self.dom_fallback = DOMFallbackClicker(driver)

    async def explore(
        self, 
        targets: List[Dict[str, Any]], 
        nav_type: str, 
        initial_hash: str
    ) -> List[Dict[str, Any]]:
        """
        Itera sobre os alvos, clica e captura páginas novas.
        
        Args:
            targets: Lista de alvos identificados pelo Scout.
            nav_type: Tipo de navegação ("native_footer", "top_tabs", etc).
            initial_hash: Hash da página inicial (Home) para deduplicação.
            
        Returns:
            Lista de dicionários contendo metadados e bytes das páginas encontradas (Excluindo a Home).
        """
        seen_hashes = [initial_hash]
        new_pages = []

        for i, target in enumerate(targets):
            logger.info(f"--- Explorando alvo {i+1}/{len(targets)}: {target.get('label')} ---")

            # Lógica de Clique: DOM Primeiro para Nativo, Visual Primeiro para Customizado
            result = None
            if nav_type == "native_footer":
                # TENTATIVA 1: Clique Nativo (DOM)
                result = await self.dom_fallback.try_dom_click(seen_hashes, nav_type)
                
                # TENTATIVA 2: Fallback Visual (apenas se DOM falhar)
                if not result.success:
                    logger.warning(f"⚠️ Clique nativo falhou para '{target.get('label')}'. Tentando visual...")
                    result = await self.clicker.click_with_retry(
                        target['x'], target['y'],
                        seen_hashes,
                        nav_type
                    )
            else:
                # Lógica Padrão (Visual Primeiro)
                result = await self.clicker.click_with_retry(
                    target['x'], target['y'],
                    seen_hashes,
                    nav_type
                )
            
            # Se ainda falhou, desiste desse alvo
            if not result.success:
                logger.error(f"💀 Alvo '{target.get('label')}' ignorado definitivamente.")
                continue
            
            # SE CHEGOU AQUI, É UMA PÁGINA VÁLIDA NOVA
            seen_hashes.append(result.phash)
            
            # Salva imagem e registra
            filename = f"{i+1:02d}_target.png"
            (self.img_dir / filename).write_bytes(result.screenshot_bytes)
            
            new_pages.append({
                "id": i+1,
                "label": target.get("label", f"Page {i+1}"),
                "bytes": result.screenshot_bytes,
                "filename": filename,
                "hash": str(result.phash)
            })

        return new_pages
