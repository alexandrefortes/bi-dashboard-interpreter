"""
Teste ISOLADO: Scroll no container principal do Power BI.
Capturar painel inteiro mesmo se for verticalmente scrollável.
"""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright
from PIL import Image
import io

# ========== CONFIGURAÇÕES ==========
URL_DO_PAINEL = "https://app.powerbi.com/view?r=eyJrIjoiM2YyOWM0ODItZmM4OC00ZmYxLTlmMmQtOTNlNGE0MTkyNGZkIiwidCI6ImVjYjc2ZjQ4LTAxN2YtNGZmMy05NzNkLTgzMWFiNDcwZjE2ZiJ9"
OUTPUT_DIR = Path("screenshots_scroll_test")
VIEWPORT_WIDTH = 1920
VIEWPORT_HEIGHT = 1080
SCROLL_PAUSE_MS = 600  # Tempo para renderização após scroll
OVERLAP_PX = 150  # Overlap entre capturas para evitar cortes


async def find_main_scroll_container(page):
    """
    Encontra o container principal com scroll vertical.
    Retorna o seletor e as dimensões.
    """
    result = await page.evaluate("""() => {
        const allElements = document.querySelectorAll('*');
        let bestMatch = null;
        let maxScrollHeight = 0;
        
        for (const el of allElements) {
            const hasVScroll = el.scrollHeight > el.clientHeight + 10;
            if (hasVScroll && el.scrollHeight > maxScrollHeight) {
                // Verifica se é visível e grande o suficiente
                const rect = el.getBoundingClientRect();
                if (rect.width > 500 && rect.height > 300) {
                    maxScrollHeight = el.scrollHeight;
                    
                    // Gera um seletor único
                    let selector = el.tagName.toLowerCase();
                    if (el.id) {
                        selector = '#' + el.id;
                    } else if (el.className) {
                        const classes = el.className.toString().split(/\\s+/).filter(c => c && !c.includes(':'));
                        if (classes.length > 0) {
                            selector = el.tagName.toLowerCase() + '.' + classes[0];
                        }
                    }
                    
                    bestMatch = {
                        selector: selector,
                        scrollHeight: el.scrollHeight,
                        clientHeight: el.clientHeight,
                        tagName: el.tagName,
                        id: el.id || '',
                        className: el.className ? el.className.toString().substring(0, 100) : ''
                    };
                }
            }
        }
        
        return bestMatch;
    }""")
    
    return result


async def capture_full_scroll(page, selector, scroll_height, client_height):
    """
    Captura screenshots enquanto faz scroll e une tudo.
    """
    step = client_height - OVERLAP_PX
    
    print(f"📏 Dimensões: scrollHeight={scroll_height}px, viewport={client_height}px")
    print(f"📐 Step de scroll: {step}px (overlap={OVERLAP_PX}px)")
    
    # Número estimado de capturas
    num_captures = (scroll_height // step) + 1
    print(f"📷 Capturas estimadas: {num_captures}")
    
    # Volta ao topo
    await page.evaluate(f"""() => {{
        const el = document.querySelector('{selector}');
        if (el) el.scrollTop = 0;
    }}""")
    await page.wait_for_timeout(SCROLL_PAUSE_MS)
    
    screenshots = []
    scroll_positions = []
    current_scroll = 0
    
    while True:
        # Define posição do scroll
        await page.evaluate(f"""(scrollY) => {{
            const el = document.querySelector('{selector}');
            if (el) el.scrollTop = scrollY;
        }}""", current_scroll)
        await page.wait_for_timeout(SCROLL_PAUSE_MS)
        
        # Lê posição real
        actual_scroll = await page.evaluate(f"""() => {{
            const el = document.querySelector('{selector}');
            return el ? el.scrollTop : 0;
        }}""")
        
        # Captura
        screenshot = await page.screenshot(type="png")
        screenshots.append(screenshot)
        scroll_positions.append(actual_scroll)
        
        print(f"   📸 Captura #{len(screenshots)}: scrollTop={actual_scroll}px")
        
        # Próxima posição
        current_scroll += step
        
        # Verifica se chegou no fim
        max_scroll = scroll_height - client_height
        if actual_scroll >= max_scroll - 5:
            print(f"   ✓ Fim do scroll atingido")
            break
        
        # Safety check
        if len(screenshots) > 50:
            print(f"   ⚠ Limite de segurança atingido")
            break
    
    # Volta ao topo
    await page.evaluate(f"""() => {{
        const el = document.querySelector('{selector}');
        if (el) el.scrollTop = 0;
    }}""")
    
    return screenshots, scroll_positions


def stitch_screenshots(screenshots, scroll_positions, client_height, scroll_height):
    """
    Une as screenshots baseado nas posições de scroll.
    """
    if len(screenshots) == 1:
        return Image.open(io.BytesIO(screenshots[0]))
    
    images = [Image.open(io.BytesIO(b)) for b in screenshots]
    width = images[0].width
    img_height = images[0].height
    
    # Calcula altura final baseado no scroll_height
    # Note: scroll_height inclui a área não visível
    final_height = scroll_height
    
    print(f"🧵 Unindo {len(images)} imagens")
    print(f"   Tamanho final: {width}x{final_height}px")
    
    final_image = Image.new("RGB", (width, final_height), (255, 255, 255))
    
    for i, (img, scroll_pos) in enumerate(zip(images, scroll_positions)):
        # A posição Y na imagem final é igual à posição de scroll
        y_in_final = int(scroll_pos)
        
        # Quanto da imagem podemos colar
        available_space = final_height - y_in_final
        crop_height = min(img_height, available_space)
        
        if crop_height > 0:
            cropped = img.crop((0, 0, width, crop_height))
            final_image.paste(cropped, (0, y_in_final))
            
            if i == 0:
                print(f"   Imagem {i+1}: colada em y=0")
            else:
                print(f"   Imagem {i+1}: colada em y={y_in_final}")
    
    return final_image


async def main():
    OUTPUT_DIR.mkdir(exist_ok=True)
    
    async with async_playwright() as p:
        print("=" * 60)
        print("TESTE ISOLADO: Scroll Container")
        print("=" * 60)
        
        print("\n1. Iniciando Browser...")
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT}
        )
        page = await context.new_page()
        
        print(f"2. Acessando: {URL_DO_PAINEL}")
        await page.goto(URL_DO_PAINEL, wait_until="networkidle", timeout=60000)
        
        print("3. Aguardando carregamento...")
        await page.wait_for_timeout(8000)
        
        print("\n4. Buscando container principal...")
        container = await find_main_scroll_container(page)
        
        if not container:
            print("❌ Nenhum container com scroll encontrado!")
            await browser.close()
            return
        
        print(f"   ✓ Encontrado: {container['selector']}")
        print(f"   Tag: {container['tagName']}")
        print(f"   ID: {container['id']}")
        print(f"   Classes: {container['className'][:60]}...")
        
        print("\n5. Capturando com scroll...")
        screenshots, positions = await capture_full_scroll(
            page, 
            container['selector'],
            container['scrollHeight'],
            container['clientHeight']
        )
        
        print(f"\n6. Unindo {len(screenshots)} capturas...")
        final_image = stitch_screenshots(
            screenshots, 
            positions, 
            container['clientHeight'],
            container['scrollHeight']
        )
        
        # Salva resultado
        output_path = OUTPUT_DIR / "full_scroll_result.png"
        final_image.save(output_path, "PNG")
        print(f"\n✅ RESULTADO SALVO: {output_path}")
        print(f"   Tamanho: {final_image.width}x{final_image.height}px")
        
        # Salva também as capturas individuais para debug
        debug_dir = OUTPUT_DIR / "debug"
        debug_dir.mkdir(exist_ok=True)
        for i, (ss, pos) in enumerate(zip(screenshots, positions)):
            (debug_dir / f"capture_{i:02d}_scroll{int(pos)}.png").write_bytes(ss)
        print(f"   Capturas individuais salvas em: {debug_dir}")
        
        print("\n" + "=" * 60)
        print("Navegador aberto para inspeção. Ctrl+C para fechar.")
        print("=" * 60)
        
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            pass
        
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())