"""
Estratégia de clique com retries usando círculos concêntricos.

Este módulo encapsula a lógica de tentativas de clique quando o clique
visual baseado em coordenadas do LLM não é preciso o suficiente.
"""

import asyncio
from dataclasses import dataclass
from typing import List, Tuple, Optional

from utils import setup_logger, bytes_to_image, compute_phash, is_error_screen
from config import DUPLICATE_THRESHOLD

logger = setup_logger("ClickStrategy")


def generate_concentric_offsets(max_radius: int = 40, step: int = 10) -> List[Tuple[int, int]]:
    """
    Gera offsets em círculos concêntricos.
    
    Primeiro testa o centro, depois expande em anéis com 8 direções cada.
    Mais robusto que a cruz fixa para alvos pequenos.
    
    Args:
        max_radius: Raio máximo em pixels.
        step: Incremento do raio entre anéis.
        
    Returns:
        Lista de tuplas (offset_x, offset_y).
    """
    offsets = [(0, 0)]  # Centro primeiro
    
    for radius in range(step, max_radius + 1, step):
        # 8 direções por anel (N, NE, E, SE, S, SW, W, NW)
        offsets.extend([
            (0, -radius),       # N
            (radius, -radius),  # NE  
            (radius, 0),        # E
            (radius, radius),   # SE
            (0, radius),        # S
            (-radius, radius),  # SW
            (-radius, 0),       # W
            (-radius, -radius)  # NW
        ])
    
    return offsets


@dataclass
class ClickResult:
    """Resultado de uma tentativa de clique."""
    success: bool
    screenshot_bytes: Optional[bytes] = None
    phash: Optional[object] = None
    offset_used: Tuple[int, int] = (0, 0)


class ConcentricSearchClicker:
    """
    Estratégia de clique com retries usando círculos concêntricos.
    
    Quando o clique na coordenada exata não funciona, tenta offsets
    ao redor em anéis concêntricos com 8 direções por anel.
    
    Attributes:
        driver: Instância do BrowserDriver para executar cliques.
        offsets: Lista de tuplas (offset_x, offset_y) em pixels.
        viewport: Dict com 'width' e 'height' do viewport.
    """
    
    def __init__(self, driver, offsets: List[Tuple[int, int]], viewport: dict):
        """
        Inicializa o ConcentricSearchClicker.
        
        Args:
            driver: BrowserDriver para executar ações no navegador.
            offsets: Lista de offsets em pixels, ex: [(0,0), (0,-20), (0,20), (-20,0), (20,0)]
            viewport: Dict com dimensões do viewport {'width': 1920, 'height': 1080}
        """
        self.driver = driver
        self.offsets = offsets
        self.viewport = viewport

    def _pixel_to_percentage(self, offset_x: int, offset_y: int) -> Tuple[float, float]:
        """Converte offset de pixels para porcentagem do viewport."""
        pct_x = offset_x / self.viewport['width']
        pct_y = offset_y / self.viewport['height']
        return pct_x, pct_y

    def _is_duplicate(self, current_hash, seen_hashes: list) -> bool:
        """Verifica se o hash atual é duplicata de algum já visto."""
        for seen_hash in seen_hashes:
            if current_hash - seen_hash < DUPLICATE_THRESHOLD:
                return True
        return False

    async def click_with_retry(
        self,
        target_x: float,
        target_y: float,
        seen_hashes: list,
        nav_type: str = "default",
        base_wait: float = 3.0,
        retry_wait: float = 2.0
    ) -> ClickResult:
        """
        Tenta clicar no alvo usando offsets em cruz até obter uma página diferente.
        
        Args:
            target_x: Coordenada X do alvo em porcentagem (0.0 a 1.0).
            target_y: Coordenada Y do alvo em porcentagem (0.0 a 1.0).
            seen_hashes: Lista de hashes já vistos para verificação de duplicata.
            nav_type: Tipo de navegação para cálculo do phash.
            base_wait: Tempo de espera (segundos) após primeiro clique.
            retry_wait: Tempo de espera (segundos) após cliques de retry.
            
        Returns:
            ClickResult indicando sucesso/falha e dados da screenshot.
        """
        for attempt_idx, (off_x, off_y) in enumerate(self.offsets):
            # Converte offset de pixels para porcentagem
            pct_off_x, pct_off_y = self._pixel_to_percentage(off_x, off_y)
            adj_x = target_x + pct_off_x
            adj_y = target_y + pct_off_y
            
            if attempt_idx > 0:
                logger.info(f"🔄 Tentativa {attempt_idx} (Offset {off_x}px, {off_y}px)...")
            
            # Executa clique
            await self.driver.click_at_percentage(adj_x, adj_y)
            
            # Espera carregar (retry é mais rápido)
            wait_time = base_wait if attempt_idx == 0 else retry_wait
            await asyncio.sleep(wait_time)
            
            # Captura screenshot
            shot_bytes = await self.driver.get_full_page_screenshot_bytes()
            shot_pil = bytes_to_image(shot_bytes)
            
            # Verifica tela de erro
            if is_error_screen(shot_pil):
                logger.warning("Tela de erro. Tentando próximo offset...")
                continue
            
            # Calcula hash e verifica duplicata
            current_hash = compute_phash(shot_pil, nav_type)
            
            if not self._is_duplicate(current_hash, seen_hashes):
                # SUCESSO! A página mudou.
                logger.info(f"✅ Clique funcionou (com offset {off_x},{off_y})!")
                
                # Aguarda estabilização visual antes da captura final
                await self.driver._wait_for_visual_stability(
                    max_wait_seconds=15.0,
                    check_interval=1.0,
                    stability_threshold=5
                )
                
                # Recaptura screenshot após estabilização
                shot_bytes = await self.driver.get_full_page_screenshot_bytes()
                shot_pil = bytes_to_image(shot_bytes)
                current_hash = compute_phash(shot_pil, nav_type)
                
                return ClickResult(
                    success=True,
                    screenshot_bytes=shot_bytes,
                    phash=current_hash,
                    offset_used=(off_x, off_y)
                )
            else:
                if attempt_idx == 0:
                    logger.warning("⚠️ Clique original não alterou a página. Iniciando busca em círculos concêntricos...")
        
        # Todas as tentativas falharam
        return ClickResult(success=False)


class DOMFallbackClicker:
    """
    Estratégia de fallback usando seletores DOM nativos.
    
    Usada quando a estratégia de clique visual falha para navegação
    nativa do Power BI.
    """
    
    def __init__(self, driver):
        """
        Inicializa o DOMFallbackClicker.
        
        Args:
            driver: BrowserDriver com método try_click_native_next_button.
        """
        self.driver = driver

    def _is_duplicate(self, current_hash, seen_hashes: list) -> bool:
        """Verifica se o hash atual é duplicata de algum já visto."""
        for seen_hash in seen_hashes:
            if current_hash - seen_hash < DUPLICATE_THRESHOLD:
                return True
        return False

    async def try_dom_click(
        self,
        seen_hashes: list,
        nav_type: str = "default",
        wait_after_click: float = 5.0
    ) -> ClickResult:
        """
        Tenta clicar no botão de próxima página via DOM.
        
        Args:
            seen_hashes: Lista de hashes já vistos para verificação.
            nav_type: Tipo de navegação para cálculo do phash.
            wait_after_click: Tempo de espera após o clique DOM.
            
        Returns:
            ClickResult indicando sucesso/falha.
        """
        logger.info("🚑 Tentando resgate com clique nativo via DOM...")
        
        clicked = await self.driver.try_click_native_next_button()
        
        if not clicked:
            return ClickResult(success=False)
        
        await asyncio.sleep(wait_after_click)
        
        shot_bytes = await self.driver.get_full_page_screenshot_bytes()
        shot_pil = bytes_to_image(shot_bytes)
        current_hash = compute_phash(shot_pil, nav_type)
        
        if not self._is_duplicate(current_hash, seen_hashes):
            logger.info("✅ Resgate DOM funcionou!")
            
            # Aguarda estabilização visual antes da captura final
            await self.driver._wait_for_visual_stability(
                max_wait_seconds=15.0,
                check_interval=1.0,
                stability_threshold=5
            )
            
            # Recaptura screenshot após estabilização
            shot_bytes = await self.driver.get_full_page_screenshot_bytes()
            shot_pil = bytes_to_image(shot_bytes)
            current_hash = compute_phash(shot_pil, nav_type)
            
            return ClickResult(
                success=True,
                screenshot_bytes=shot_bytes,
                phash=current_hash,
                offset_used=(0, 0)
            )
        
        return ClickResult(success=False)
