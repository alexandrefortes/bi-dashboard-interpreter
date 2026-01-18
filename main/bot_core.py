import asyncio
import io
from typing import Optional, List, Tuple, Dict, Any
from playwright.async_api import async_playwright
from PIL import Image
from config import VIEWPORT
from utils import setup_logger, are_urls_equivalent

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
        self.owns_context = False  # Flag para controlar se podemos fechar o contexto

    async def start(self, headless: bool = True, browser_instance: Any = None, context_instance: Any = None) -> None:
        """Inicia o Playwright (ou anexa a um browser/contexto existente)."""
        
        # 1. Se receber um CONTEXTO já pronto (Sessão Compartilhada)
        if context_instance:
            logger.info("♻️ Anexando a CONTEXTO compartilhado (Sessão Persistente)...")
            self.context = context_instance
            self.browser = context_instance.browser
            self.owns_context = False  # NÃO podemos fechar contexto compartilhado!
            # Cria apenas uma nova página dentro desse contexto (mantendo cookies)
            self.page = await self.context.new_page()
            return

        # 2. Se receber um BROWSER (Sessão Isolada por Contexto)
        if browser_instance:
            logger.info("Anexando a navegador compartilhado (Novo Contexto)...")
            self.browser = browser_instance
            # Não iniciamos self.playwright aqui pois é gerenciado externamente
        else:
            self.playwright = await async_playwright().start()
            logger.info(f"Iniciando navegador dedicado (Headless: {headless})...")
            
            # Argumentos para tentar diminuir detecção de automação (evitar bloqueio Google)
            launch_args = [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-infobars"
            ]
            
            # Tenta usar Chrome instalado no sistema para passar validações de "Secure Browser"
            # O bundled Chromium é frequentemente bloqueado pelo Google Login.
            try:
                self.browser = await self.playwright.chromium.launch(
                    headless=headless,
                    channel="chrome", # Tenta usar Google Chrome instalado
                    args=launch_args,
                    ignore_default_args=["--enable-automation"]
                )
                logger.info("✅ Google Chrome (System) iniciado com sucesso.")
            except Exception as e:
                logger.warning(f"⚠️ Falha ao iniciar Chrome do sistema ({e}). Tentando Chromium bundled...")
                self.browser = await self.playwright.chromium.launch(
                    headless=headless,
                    args=launch_args
                )
        
        # Cria contexto com Full HD forçado e User Agent realístico
        self.context = await self.browser.new_context(
            viewport=VIEWPORT,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        self.page = await self.context.new_page()

    async def navigate_and_stabilize(self, url: str) -> bool:
        """
        Navega para URL. Se cair em tela de login, espera o humano logar.
        """
        logger.info(f"Navegando para: {url}")
        try:
            # 1. Tenta ir para a URL
            await self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
            
            # 2. Navegação Orientada ao Alvo (Robustez)
            # Verifica se estamos na URL correta (mesmo path e params obrigatórios)
            # Se não estiver, assume que é login/SSO/Check e espera o humano resolver.
            
            if not are_urls_equivalent(url, self.page.url):
                logger.info("🛑 URL inicial difere do alvo (Login/SSO/Check detectado).")
                logger.info("⏳ Aguardando você navegar até a URL correta...")
                
                # Predicado para wait_for_url
                # Nota: precisamos capturar 'url' do escopo externo
                def is_target_url(current_u):
                    return are_urls_equivalent(url, current_u)

                # Espera indefinidamente (timeout=0) até a URL corresponder logicamente
                await self.page.wait_for_url(is_target_url, timeout=0)
                
                logger.info("✅ URL correta alcançada! Retomando automação...")
                # Pequena pausa para garantir renderização inicial pós-redirecionamento
                await asyncio.sleep(2)


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
    ) -> None:
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

    async def click_at_percentage(self, x_pct: float, y_pct: float) -> bool:
        """Clica na tela baseada em porcentagem da viewport."""
        
        # Validação defensiva: se coordenadas forem None ou inválidas, aborta
        if x_pct is None or y_pct is None:
            logger.error(f"❌ Coordenadas inválidas recebidas: x={x_pct}, y={y_pct}. Abortando clique.")
            return False
        
        if not isinstance(x_pct, (int, float)) or not isinstance(y_pct, (int, float)):
            logger.error(f"❌ Coordenadas não numéricas: x={type(x_pct)}, y={type(y_pct)}. Abortando clique.")
            return False
        
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

    async def get_screenshot_bytes(self) -> bytes:
        """Retorna bytes da screenshot PNG (viewport atual)."""
        return await self.page.screenshot(type="png")

    async def get_full_page_screenshot_bytes(self) -> bytes:
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

    async def _find_scroll_container(self, min_area_ratio: float = 0.6) -> Optional[Dict[str, Any]]:
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

    async def _capture_with_scroll(self, selector: str, scroll_height: int, client_height: int) -> Tuple[List[bytes], List[int]]:
        """Captura screenshots enquanto faz scroll."""
        step = client_height - SCROLL_OVERLAP_PX
        
        # Volta ao topo
        await self.page.evaluate(f"""() => {{
            const el = document.querySelector('{selector}');
            if (el) el.scrollTop = 0;
        }}""")
        
        # Aguarda estabilização visual no topo
        await self._wait_for_visual_stability(
            max_wait_seconds=10.0, # Aumentado para Batch Mode
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
                max_wait_seconds=8.0,  # Aumentado para Batch Mode
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

    def _stitch_screenshots(self, screenshots: List[bytes], positions: List[int], client_height: int, scroll_height: int) -> Image.Image:
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

    async def close(self) -> None:
        """Fecha o navegador e libera recursos."""
        # Se estamos usando contexto compartilhado, só fechamos a PÁGINA (tab)
        # para não matar os outros workers
        if not self.owns_context:
            if self.page and not self.page.is_closed():
                await self.page.close()
            return
        
        # Se somos donos do contexto, fechamos tudo
        if self.context: 
            await self.context.close()
        
        # Só fechamos o browser/playwright se nós o criamos (self.playwright existe)
        if self.playwright:
            if self.browser: 
                await self.browser.close()
            await self.playwright.stop()
    
    async def try_click_native_next_button(self) -> bool:
        """
        Tenta clicar no botão nativo de próxima página via DOM selector.
        Otimizado com base no HTML real extraído.
        """
        try:
            # Lista de seletores ordenados por precisão baseada no seu HTML
            selectors = [
                "button[aria-label='Próxima Página']",
                "button[aria-label='Next Page']",
                "button i.pbi-glyph-chevronrightmedium",
                ".pbi-glyph-chevronrightmedium",
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

    async def get_databricks_tabs(self) -> List[Dict[str, Any]]:
        """
        Escaneia o DOM em busca de abas nativas do Databricks (role='tab').
        Retorna lista de targets prontos para o Explorer.
        """
        logger.info("🕵️ Escaneando abas do Databricks via DOM...")
        
        # Script para extrair dados das abas
        # Procura button[role='tab'] dentro de div[role='tablist']
        # Retorna: Text, Selected (bool), Selector (id)
        tabs_data = await self.page.evaluate("""() => {
            const tabs = Array.from(document.querySelectorAll("div[role='tablist'] button[role='tab']"));
            
            return tabs.map(t => {
                // Tenta pegar titulo do span interno ou do proprio botao ou title
                let label = t.innerText || t.getAttribute('title') || 'Tab';
                
                // Limpa quebras de linha
                label = label.replace(/[\\n\\r]+/g, ' ').trim();
                
                // Seletor único (ID é o melhor se existir)
                let selector = '';
                if (t.id) {
                    selector = '#' + CSS.escape(t.id);
                } else {
                    // Fallback para atributo data-navigation-tab-id
                    const navId = t.getAttribute('data-navigation-tab-id');
                    if (navId) {
                        selector = `button[data-navigation-tab-id="${CSS.escape(navId)}"]`;
                    }
                }

                // Pega posições para fallback visual
                const rect = t.getBoundingClientRect();
                const x_pct = (rect.left + rect.width / 2) / window.innerWidth;
                const y_pct = (rect.top + rect.height / 2) / window.innerHeight;

                return {
                    label: label,
                    selector: selector,
                    is_active: t.getAttribute('aria-selected') === 'true',
                    x: x_pct,
                    y: y_pct
                };
            });
        }""")
        
        logger.info(f"Databricks: {len(tabs_data)} abas encontradas.")
        
        # Filtra abas válidas e formata para o padrão do sistema
        targets = []
        for t in tabs_data:
            # Adiciona metadados extras para o clique preciso
            targets.append({
                "label": t['label'],
                "x": t['x'], 
                "y": t['y'],
                "selector": t['selector'], # Explorer pode usar isso para clique direto!
                "type": "databricks_tab"
            })
            
        return targets

    async def click_element(self, selector: str) -> bool:
        """Clica em um elemento específico via Seletor CSS."""
        try:
            logger.info(f"Clicando via seletor: {selector}")
            if not selector:
                return False
            await self.page.click(selector)
            return True
        except Exception as e:
            logger.error(f"Erro ao clicar no seletor '{selector}': {e}")
            return False