import asyncio
from playwright.async_api import async_playwright

# --- CONFIGURAÇÕES ---
URL_DO_PAINEL = "https://app.powerbi.com/view?r=eyJrIjoiODkxNjY2YWQtMGUxZi00NDRhLTlmMTctZmQ1OTk0YzBlOTNmIiwidCI6ImVhZTA3OGZkLTQxMjQtNGNmYi1hYTYzLTRjNTliNTAyODVhOSIsImMiOjEwfQ%3D%3D"  
ARQUIVO_PRINT = "dashboard_fullhd.png"
# ---------------------

async def main():
    async with async_playwright() as p:
        print("1. Iniciando Browser...")
        # headless=False para ver o navegador
        browser = await p.chromium.launch(headless=False)
        
        # Cria uma página já com a resolução Full HD (1920x1080)
        page = await browser.new_page(viewport={'width': 1920, 'height': 1080})
        
        print(f"2. Acessando: {URL_DO_PAINEL}")
        await page.goto(URL_DO_PAINEL)
        
        print("3. Aguardando carregamento completo...")
        # 'networkidle' espera até que não haja mais conexões de rede (ideal para dashboards)
        try:
            await page.wait_for_load_state("networkidle", timeout=10000) # espera até 10s
        except:
            print("Alerta: O carregamento de rede demorou, mas vamos prosseguir.")
        
        # Espera forçada de 5 segundos para garantir animações ou gráficos lentos
        await asyncio.sleep(5)
        
        print("4. Tirando Print...")
        await page.screenshot(path=ARQUIVO_PRINT)
        print(f"Print salvo em: {ARQUIVO_PRINT}")
        
        print("-" * 30)
        print("O NAVEGADOR ESTÁ ABERTO.")
        print("Pressione Ctrl+C no terminal para encerrar o script e fechar o navegador.")
        print("-" * 30)
        
        # Truque para manter o script rodando e o browser aberto para sempre
        # O script só para se você der erro ou forçar a parada
        await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nEncerrando script...")