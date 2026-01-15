import asyncio
from playwright.async_api import async_playwright
from config import VIEWPORT
from utils import setup_logger

logger = setup_logger("BotCore")

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

            # 3. Estabilização Padrão (igual ao código anterior)
            logger.info("Aguardando networkidle...")
            try:
                await self.page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                logger.warning("Networkidle timeout (prosseguindo)")

            logger.info("Aguardando renderização final (sleep 5s)...")
            await asyncio.sleep(5)
            
            return True

        except Exception as e:
            logger.error(f"Erro na navegação: {e}")
            return False

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
        """Retorna bytes da screenshot PNG."""
        return await self.page.screenshot(type="png")

    async def close(self):
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