import asyncio
import io
from playwright.async_api import async_playwright
from PIL import Image
from config import VIEWPORT
from utils import setup_logger

logger = setup_logger("BotCore")

# Configurações de scroll screenshot
SCROLL_PAUSE_MS = 600  # Tempo para renderização após scroll
SCROLL_OVERLAP_PX = 150  # Overlap entre capturas para evitar cortes


class BrowserDriver:
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    async def start(self, headless=True):
        """Inicia o Playwright."""
        self.playwright = await async_playwright().start()
        logger.info(f"Iniciando navegador (Headless: {headless})...")
        self.browser = await self.playwright.chromium.launch(headless=headless)
        
        # Cria contexto com Full HD forçado
        self.context = await self.browser.new_context(viewport=VIEWPORT)
        self.page = await self.context.new_page()

    async def navigate_and_stabilize(self, url):
        """
        Navega para URL. Se cair em tela de login, espera o humano logar.
        """
        logger.info(f"Navegando para: {url}")
        try:
            # 1. Tenta ir para a URL
            await self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
            
            # 2. Verifica se fomos redirecionados para Login da Microsoft/SSO
            # URLs comuns de login: login.microsoftonline.com, accounts.google.com, etc.
            current_url = self.page.url
            if "login.microsoftonline" in current_url or "signin" in current_url or "oauth" in current_url:
                logger.info("🛑 TELA DE LOGIN DETECTADA!")
                logger.info("👉 Por favor, faça o login manualmente na janela do navegador.")
                logger.info("⏳ O robô só vai continuar quando você estiver na URL correta, o link do primeiro painel do vetor de URLs (urls.json).")                

                # Espera indefinidamente (timeout=0) até a URL voltar a ser do Power BI
                # Só acorda se a URL atual contiver a URL alvo
                await self.page.wait_for_url(
                    lambda current_u: url.strip() in current_u, 
                    timeout=0
                )
                
                logger.info("✅ Login e URL correta detectados! Retomando automação...")
                # Pequena pausa para garantir que o redirecionamento pós-login terminou
                await asyncio.sleep(5)

            # 3. Estabilização Padrão
            logger.info("Aguardando networkidle...")
            try:
                await self.page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                logger.warning("Networkidle timeout (prosseguindo)")

            # 4. Estabilização Visual - espera visuais terminarem de renderizar
            await self._wait_for_visual_stability()
            
            return True

        except Exception as e:
            logger.error(f"Erro na navegação: {e}")
            return False

    async def _wait_for_visual_stability(
        self, 
        max_wait_seconds: float = 30.0, 
        check_interval: float = 1.0,
        stability_threshold: int = 5
    ):
        """
        Aguarda até que a página pare de mudar visualmente.
        
        Útil para dashboards com visuais assíncronos (mapas, gráficos animados).
        Compara screenshots consecutivas usando perceptual hash.
        
        Args:
            max_wait_seconds: Tempo máximo de espera em segundos.
            check_interval: Intervalo entre verificações em segundos.
            stability_threshold: Diferença máxima de hash para considerar estável.
        """
        from utils import bytes_to_image, compute_phash
        
        logger.info("⏳ Aguardando estabilidade visual...")
        
        start_time = asyncio.get_event_loop().time()
        previous_hash = None
        stable_count = 0
        stable_needed = 2  # Precisa de 2 leituras estáveis consecutivas
        
        while (asyncio.get_event_loop().time() - start_time) < max_wait_seconds:
            # Captura screenshot atual
            shot_bytes = await self.page.screenshot(type="png")
            shot_pil = bytes_to_image(shot_bytes)
            current_hash = compute_phash(shot_pil)
            
            if previous_hash is not None:
                diff = current_hash - previous_hash
                
                if diff <= stability_threshold:
                    stable_count += 1
                    logger.debug(f"Visual estável ({stable_count}/{stable_needed}), diff={diff}")
                    
                    if stable_count >= stable_needed:
                        elapsed = asyncio.get_event_loop().time() - start_time
                        logger.info(f"✅ Página estabilizada em {elapsed:.1f}s")
                        return
                else:
                    stable_count = 0
                    logger.debug(f"Visual ainda mudando (diff={diff}), aguardando...")
            
            previous_hash = current_hash
            await asyncio.sleep(check_interval)
        
        logger.warning(f"⚠️ Timeout de estabilidade visual ({max_wait_seconds}s) - prosseguindo mesmo assim")

    async def click_at_percentage(self, x_pct, y_pct):
        """Clica na tela baseada em porcentagem da viewport."""
        width = VIEWPORT['width']
        height = VIEWPORT['height']
        
        x = int(width * x_pct)
        y = int(height * y_pct)
        
        logger.info(f"Clicando em ({x}, {y}) [{x_pct*100:.1f}%, {y_pct*100:.1f}%]")
        
        try:
            await self.page.mouse.click(x, y)
            return True
        except Exception as e:
            logger.error(f"Erro ao clicar: {e}")
            return False

    async def get_screenshot_bytes(self):
        """Retorna bytes da screenshot PNG (viewport atual)."""
        return await self.page.screenshot(type="png")

    async def get_full_page_screenshot_bytes(self):
        """
        Retorna bytes da screenshot PNG da página completa.
        
        Se a página tiver scroll vertical, faz múltiplas capturas
        enquanto rola e une tudo em uma imagem única.
        
        Ideal para dashboards Power BI extensos verticalmente.
        """
        # 1. Encontra o container principal com scroll
        container_info = await self._find_scroll_container()
        
        if not container_info or not container_info.get('canScroll'):
            # Não tem scroll que atinja o critério de área mínima
            return await self.page.screenshot(type="png")
        
        selector = container_info['selector']
        scroll_height = container_info['scrollHeight']
        client_height = container_info['clientHeight']
        area_ratio = container_info.get('areaRatio', '?')
        
        logger.info(f"Scroll detectado em '{selector}' (area={area_ratio}%, scrollH={scroll_height}px)")
        
        # 2. Captura com scroll
        screenshots, positions = await self._capture_with_scroll(
            selector, scroll_height, client_height
        )
        
        if len(screenshots) == 1:
            return screenshots[0]
        
        # 3. Une as imagens
        logger.info(f"Unindo {len(screenshots)} capturas...")
        final_image = self._stitch_screenshots(screenshots, positions, client_height, scroll_height)
        
        # 4. Converte para bytes
        output_buffer = io.BytesIO()
        final_image.save(output_buffer, format="PNG")
        return output_buffer.getvalue()

    async def _find_scroll_container(self, min_area_ratio: float = 0.6):
        """
        Encontra o container principal com scroll vertical.
        
        Retorna o elemento com scroll de maior área que ocupe >= min_area_ratio do viewport.
        """
        return await self.page.evaluate("""(minAreaRatio) => {
            const viewportArea = window.innerWidth * window.innerHeight;
            let best = null;
            let bestArea = 0;
            
            for (const el of document.querySelectorAll('*')) {
                const hasVScroll = el.scrollHeight > el.clientHeight + 10;
                if (!hasVScroll) continue;
                
                const rect = el.getBoundingClientRect();
                if (rect.width < 100 || rect.height < 100) continue;
                
                const elementArea = rect.width * rect.height;
                const areaRatio = elementArea / viewportArea;
                
                // Só considera se atinge o critério mínimo de área
                if (areaRatio < minAreaRatio) continue;
                
                // Guarda o de maior área (mais resiliente que "primeiro encontrado")
                if (elementArea > bestArea) {
                    bestArea = elementArea;
                    
                    let selector = el.tagName.toLowerCase();
                    if (el.id) {
                        selector = '#' + el.id;
                    } else if (el.className) {
                        const classes = el.className.toString().split(/\\s+/).filter(c => c && !c.includes(':'));
                        if (classes.length > 0) {
                            selector = el.tagName.toLowerCase() + '.' + classes[0];
                        }
                    }
                    
                    best = {
                        selector: selector,
                        scrollHeight: el.scrollHeight,
                        clientHeight: el.clientHeight,
                        canScroll: true,
                        areaRatio: Math.round(areaRatio * 100)
                    };
                }
            }
            
            return best;
        }""", min_area_ratio)

    async def _capture_with_scroll(self, selector, scroll_height, client_height):
        """Captura screenshots enquanto faz scroll."""
        step = client_height - SCROLL_OVERLAP_PX
        
        # Volta ao topo
        await self.page.evaluate(f"""() => {{
            const el = document.querySelector('{selector}');
            if (el) el.scrollTop = 0;
        }}""")
        
        # Aguarda estabilização visual no topo
        await self._wait_for_visual_stability(
            max_wait_seconds=5.0,
            check_interval=0.5,
            stability_threshold=3
        )
        
        screenshots = []
        positions = []
        current_scroll = 0
        max_scroll = scroll_height - client_height
        
        while True:
            # Define posição do scroll
            await self.page.evaluate(f"""(scrollY) => {{
                const el = document.querySelector('{selector}');
                if (el) el.scrollTop = scrollY;
            }}""", current_scroll)
            
            # Estabilização visual leve para cada posição de scroll
            await self._wait_for_visual_stability(
                max_wait_seconds=5.0,  # Timeout curto para scroll
                check_interval=0.5,
                stability_threshold=3  # Mais sensível
            )
            
            # Lê posição real
            actual_scroll = await self.page.evaluate(f"""() => {{
                const el = document.querySelector('{selector}');
                return el ? el.scrollTop : 0;
            }}""")
            
            # Captura
            screenshot = await self.page.screenshot(type="png")
            screenshots.append(screenshot)
            positions.append(actual_scroll)
            
            logger.debug(f"Captura #{len(screenshots)}: scrollTop={actual_scroll}px")
            
            # Próxima posição
            current_scroll += step
            
            # Verifica se chegou no fim
            if actual_scroll >= max_scroll - 5:
                break
            
            # Safety check
            if len(screenshots) > 50:
                logger.warning("Limite de capturas de scroll atingido (50)")
                break
        
        # Volta ao topo
        await self.page.evaluate(f"""() => {{
            const el = document.querySelector('{selector}');
            if (el) el.scrollTop = 0;
        }}""")
        
        return screenshots, positions

    def _stitch_screenshots(self, screenshots, positions, client_height, scroll_height):
        """Une múltiplas screenshots baseado nas posições de scroll."""
        images = [Image.open(io.BytesIO(b)) for b in screenshots]
        
        width = images[0].width
        final_height = scroll_height
        
        final_image = Image.new("RGB", (width, final_height), (255, 255, 255))
        
        for i, (img, scroll_pos) in enumerate(zip(images, positions)):
            y_in_final = int(scroll_pos)
            
            # Quanto da imagem podemos colar
            available_space = final_height - y_in_final
            crop_height = min(img.height, available_space)
            
            if crop_height > 0:
                cropped = img.crop((0, 0, width, crop_height))
                final_image.paste(cropped, (0, y_in_final))
        
        return final_image

    async def close(self):
        """Fecha o navegador e libera recursos."""
        if self.context: await self.context.close()
        if self.browser: await self.browser.close()
        if self.playwright: await self.playwright.stop()
    
    async def try_click_native_next_button(self):
        """
        Tenta clicar no botão nativo de próxima página via DOM selector.
        Otimizado com base no HTML real extraído.
        """
        try:
            # Lista de seletores ordenados por precisão baseada no seu HTML
            selectors = [
                "button i.pbi-glyph-chevronrightmedium", # 1º - classe (agnóstico)
                ".pbi-glyph-chevronrightmedium",         # 2º - ícone direto
                "button[aria-label='Próxima Página']",   # 3º - fallback PT
                "button[aria-label='Next Page']",        # 4º - fallback EN
            ]
            
            for selector in selectors:
                # Procura o elemento
                btn = self.page.locator(selector)
                
                # Verifica se existe e se está visível
                if await btn.count() > 0 and await btn.first.is_visible():
                    logger.info(f"🔧 Fallback (DOM): Clicando no seletor '{selector}'...")
                    
                    # Force=True ajuda se houver overlay transparente
                    await btn.first.click(force=True) 
                    return True
            
            logger.warning("🔧 Fallback falhou: Nenhum seletor correspondeu ao DOM.")
            return False
            
        except Exception as e:
            logger.warning(f"Erro fatal no clique nativo: {e}")
            return False