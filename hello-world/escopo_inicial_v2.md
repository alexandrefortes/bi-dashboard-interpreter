<system_role>
Engenheiro de software especializado em Selenium e BI.
</system_role>

<Objetivo_do_sistema>
Desenvolver um agente de software capaz de acessar, navegar e catalogar painéis de Business Intelligence (inicialmente Power BI) de forma pragmática e resiliente, com foco em **catalogação macro** de estrutura e organização.

**Objetivo operacional:** Para cada URL de dashboard, produzir um catálogo composto por páginas navegáveis identificadas, com screenshots, extração de estrutura visual e classificação semântica de alto nível.

**Princípio de design:** Priorizar velocidade e cobertura sobre precisão pixel-perfect. Tolerância a falsos positivos ocasionais (botão que não leva a lugar nenhum) e falsos negativos raros (página escondida não descoberta) em troca de simplicidade de códigoe execução rápida.
</Objetivo_do_sistema>

<Input>
Um vetor de links de painéis de BI.
</Input>

<escopo_geral>
## ESCOPO MÍNIMO VIÁVEL (Piloto)

### Stack Simplificada
```python
# requirements.txt
playwright==1.40.0
pillow==10.1.0
imagehash==4.3.1
google-generativeai==0.3.0  # apenas este LLM
```

### Arquitetura Reduzida

```
┌─────────────────────────────────────────────┐
│  INPUT: Vetor de URLs do dashboard          │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│  ESTÁGIO A (Simplificado)                   │
│  - goto + networkidle                       │
│  - delay fixo 5s                            │
│  - screenshot                               │
│  - check visual básico (dominância de cor)  │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│  ESTÁGIO B (Scout - apenas 1 chamada LLM)   │
│  - Gemini: detecta nav_type + targets       │
│  - Ignora overflow                          │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│  ESTÁGIO C (Explorer Sequencial)            │
│  - Para cada target:                        │
│    1. Screenshot before                     │
│    2. Click (1 tentativa)                   │
│    3. Wait 5s                               │
│    4. Screenshot after                      │
│    5. pHash ROI diff > threshold? → válido  │
│  - SEM reset entre targets                  │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│  ESTÁGIO D (Análise)                        │
│  - Apenas para páginas válidas              │
│  - Prompt curto: título + visuais + domínio │
│  - 1 chamada Gemini por página              │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌────────────────────────────────────────────────────────────┐
│  OUTPUT: JSON (dict)                                       │
│  - Salvo com json.dump()                                   │
│  - Screenshots em pasta (nome igual a titulo do dashboard) │
└────────────────────────────────────────────────────────────┘
```

---

## CÓDIGO INICIAL DO PILOTO (DEMANDA REVISÃO)

```python
# catalogador_pilot.py

import asyncio
import json
import time
from pathlib import Path
from datetime import datetime
from PIL import Image
from imagehash import phash
import io
import google.generativeai as genai
from playwright.async_api import async_playwright

# ============================================
# CONFIGURAÇÃO
# ============================================

GEMINI_API_KEY = "your-key-here"
genai.configure(api_key=GEMINI_API_KEY)

FLASH = genai.GenerativeModel('gemini-1.5-flash')
PRO = genai.GenerativeModel('gemini-1.5-pro')

PHASH_THRESHOLD = 8  # diferença mínima para considerar mudança

ROI_CROP = {
    "bottom_tabs": (0, 0, 1, 0.90),    # remove 10% inferior
    "left_list": (0.20, 0, 1, 1),      # remove 20% esquerda
    "top_tabs": (0, 0.08, 1, 1),       # remove 8% superior
    "default": (0, 0, 1, 1)            # sem crop
}

# ============================================
# UTILITÁRIOS
# ============================================

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def crop_roi(img_bytes, nav_type):
    """Crop simples baseado em nav_type."""
    crop = ROI_CROP.get(nav_type, ROI_CROP["default"])
    img = Image.open(io.BytesIO(img_bytes))
    w, h = img.size
    
    left = int(w * crop[0])
    top = int(h * crop[1])
    right = int(w * crop[2])
    bottom = int(h * crop[3])
    
    return img.crop((left, top, right, bottom))

def compute_phash(img_bytes, nav_type="default"):
    """Hash perceptual do ROI."""
    roi = crop_roi(img_bytes, nav_type)
    return phash(roi)

def is_error_screen(img_bytes):
    """Heurística simples: muito branco ou muito vermelho = erro."""
    img = Image.open(io.BytesIO(img_bytes)).convert('RGB')
    img_small = img.resize((100, 100))
    pixels = list(img_small.getdata())
    
    # Contar pixels predominantemente brancos
    white = sum(1 for r,g,b in pixels if r > 240 and g > 240 and b > 240)
    
    # Contar pixels avermelhados (erros comuns)
    red = sum(1 for r,g,b in pixels if r > 200 and g < 100 and b < 100)
    
    # Se >80% branco ou >30% vermelho = provável erro
    return (white > 8000) or (red > 3000)

# ============================================
# ESTÁGIO A: ACESSO
# ============================================

async def open_and_stabilize(page, url):
    """Abre URL e espera carregar (versão ultra-simples)."""
    log(f"Opening {url}")
    
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    
    try:
        await page.wait_for_load_state("networkidle", timeout=10000)
    except:
        pass  # ignora timeout de networkidle
    
    await page.wait_for_timeout(5000)  # delay fixo 5s
    
    img = await page.screenshot(type="png")
    
    if is_error_screen(img):
        raise Exception("Error screen detected")
    
    return img

# ============================================
# ESTÁGIO B: SCOUT
# ============================================

async def discover_navigation(img_bytes):
    """Detecta navegação com Gemini Flash."""
    log("Discovering navigation...")
    
    img = Image.open(io.BytesIO(img_bytes))
    
    prompt = """
Identifique elementos de NAVEGAÇÃO entre páginas neste dashboard.

Retorne JSON:
{
  "nav_type": "bottom_tabs" | "left_list" | "top_tabs" | "none",
  "targets": [
    {"label": "Nome", "x": 0.5, "y": 0.95}
  ]
}

x e y são coordenadas NORMALIZADAS (0-1) do CENTRO do elemento.
Ignore filtros/slicers. Apenas navegação de páginas.
"""
    
    response = await FLASH.generate_content_async([prompt, img])
    
    # Parse JSON (sem validação rigorosa)
    text = response.text.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    
    data = json.loads(text)
    
    log(f"Found nav_type={data['nav_type']}, {len(data.get('targets', []))} targets")
    
    return data

# ============================================
# ESTÁGIO C: EXPLORER
# ============================================

async def explore_targets(page, nav_data):
    """Explora targets sequencialmente sem reset."""
    targets = nav_data.get("targets", [])
    nav_type = nav_data["nav_type"]
    
    pages = []
    
    for i, target in enumerate(targets, 1):
        log(f"Exploring {i}/{len(targets)}: {target['label']}")
        
        # Before
        before = await page.screenshot()
        hash_before = compute_phash(before, nav_type)
        
        # Click
        vp = page.viewport_size
        x = int(target["x"] * vp["width"])
        y = int(target["y"] * vp["height"])
        
        try:
            await page.mouse.click(x, y)
        except Exception as e:
            log(f"  Click failed: {e}")
            continue
        
        await page.wait_for_timeout(3000)
        
        # After
        after = await page.screenshot()
        hash_after = compute_phash(after, nav_type)
        
        diff = hash_before - hash_after
        
        if diff < PHASH_THRESHOLD:
            log(f"  No change (diff={diff})")
            continue
        
        log(f"  Valid page! (diff={diff})")
        
        pages.append({
            "id": i,
            "label": target["label"],
            "screenshot": after,
            "phash_diff": diff
        })
    
    return pages

# ============================================
# ESTÁGIO D: ANÁLISE
# ============================================

async def analyze_page(img_bytes):
    """Análise minimalista com Gemini Pro."""
    img = Image.open(io.BytesIO(img_bytes))
    
    prompt = """
Analise este dashboard. Retorne JSON:

{
  "titulo": "título visível ou null",
  "visuais": ["tipo1", "tipo2"],
  "dominio": "Financeiro|Vendas|Operações|RH|TI|Marketing|Outro"
}

Visuais: "grafico_barras", "grafico_linha", "tabela", "kpi", "mapa", etc.
Máximo 5 tipos.
"""
    
    response = await PRO.generate_content_async([prompt, img])
    
    text = response.text.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    
    return json.loads(text)

# ============================================
# ORQUESTRADOR
# ============================================

async def catalog_dashboard(url, output_dir="./runs"):
    """Pipeline completo."""
    start = time.time()
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    run_dir = Path(output_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir = run_dir / "screenshots"
    screenshots_dir.mkdir(exist_ok=True)
    
    log(f"Starting run: {run_id}")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080}
        )
        page = await context.new_page()
        
        try:
            # ESTÁGIO A
            initial_img = await open_and_stabilize(page, url)
            (screenshots_dir / "00_initial.png").write_bytes(initial_img)
            
            # ESTÁGIO B
            nav_data = await discover_navigation(initial_img)
            
            if nav_data["nav_type"] == "none":
                log("No navigation found. Single page dashboard.")
                pages_data = []
            else:
                # ESTÁGIO C
                pages_data = await explore_targets(page, nav_data)
            
            # ESTÁGIO D
            log("Analyzing pages...")
            for page_data in pages_data:
                analysis = await analyze_page(page_data["screenshot"])
                page_data["analysis"] = analysis
                
                # Salvar screenshot
                filename = f"{page_data['id']:02d}_{page_data['label'][:30]}.png"
                (screenshots_dir / filename).write_bytes(page_data["screenshot"])
                
                # Remover bytes do dict (não serializável)
                del page_data["screenshot"]
            
            # Montar catálogo
            catalog = {
                "run_id": run_id,
                "url": url,
                "timestamp": datetime.now().isoformat(),
                "duration_seconds": time.time() - start,
                "navigation": nav_data,
                "pages": pages_data,
                "summary": {
                    "targets_found": len(nav_data.get("targets", [])),
                    "pages_cataloged": len(pages_data)
                }
            }
            
            # Salvar JSON
            catalog_path = run_dir / "catalog.json"
            with open(catalog_path, "w", encoding="utf-8") as f:
                json.dump(catalog, f, indent=2, ensure_ascii=False)
            
            log(f"✅ Done! Cataloged {len(pages_data)} pages in {time.time()-start:.1f}s")
            log(f"📁 Output: {catalog_path}")
            
            return catalog
            
        finally:
            await context.close()
            await browser.close()

# ============================================
# USO
# ============================================

async def main():
    url = "https://app.powerbi.com/view?r=..."  # seu URL aqui
    
    catalog = await catalog_dashboard(url)
    
    print("\n" + "="*50)
    print("RESUMO:")
    print(f"  Páginas encontradas: {catalog['summary']['pages_cataloged']}")
    for page in catalog['pages']:
        print(f"    - {page['label']}: {page['analysis']['dominio']}")

if __name__ == "__main__":
    asyncio.run(main())
```

---

## O QUE JÁ TEM

✅ **Essencial para funcionar:**
1. Playwright (browser automation)
2. ImageHash (validação de mudança)
3. Gemini Flash (Scout) + Pro (Analyst)
4. JSON nativo (output)
5. Navegação sequencial sem reset
6. Validação por pHash único

---

## O QUE FALTA

1. Exploração sequencial → Reset entre targets (avaliar)
2. Retry de clique → avaliar se vale mais tentativas se falhar
3. Print simples → Logging estruturado
4. Aceita duplicatas → Aplicar deduplicação
5. Apenas PIL → Talvez OpenCV
6. Análise com 3 campos JSON → Analise um pouco mais completa com estrutura_visual, principais_indicadores, filtros_visiveis, dominio_negocio ("Financeiro | Vendas | Operações | ..."), publico_alvo ("Executivo | Gerencial | Operacional | Analítico"), legibilidade ("alta | média | baixa"), observacoes ("string opcional")

---

⚠️ **Limitações aceitas:**
- Ignorar páginas escondidas em overflow
- Não detecta drillthrough
</escopo_geral>