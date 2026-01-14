# ESCOPO TÉCNICO FINAL v2.0: Catalogador Autônomo de BI (Arquitetura Visual-First Simplificada)

## 1. Visão Geral e Objetivo

Desenvolver um agente de software capaz de acessar, navegar e catalogar painéis de Business Intelligence (inicialmente Power BI) de forma pragmática e resiliente, com foco em **catalogação macro** de estrutura e organização.

**Objetivo operacional:** Para cada URL de dashboard, produzir um catálogo composto por páginas navegáveis identificadas, com screenshots, extração de estrutura visual e classificação semântica de alto nível.

**Princípio de design:** Priorizar velocidade e cobertura sobre precisão pixel-perfect. Tolerância a falsos positivos ocasionais (botão que não leva a lugar nenhum) e falsos negativos raros (página escondida não descoberta) em troca de simplicidade e execução rápida.

---

## 2. Stack Tecnológica

* **Linguagem:** Python 3.10+
* **Browser Automation:** Playwright (Python API)
* **IA Multimodal:**
  * **Navegação e State Checks:** Gemini 1.5 Flash (ou GPT-4o-mini)
  * **Análise Macro de Páginas:** Gemini 1.5 Pro (ou GPT-4o)
* **Validação Visual:** OpenCV + ImageHash (pHash) + pixel diff low-res
* **Validação de Schema:** Pydantic v2
* **Persistência:** Sistema de arquivos (MVP) com opção SQLite/Parquet (escala)
* **Observabilidade:** Logging estruturado JSON por `run_id`

---

## 3. Arquitetura do Pipeline Simplificado

O pipeline opera por URL. Cada execução gera um `run_id` único para rastreabilidade completa.

### 3.1 Estágio A: Acesso e Validação de Estado (The Sentry)

**Objetivo:** Garantir que o dashboard carregou e não está em estado de erro/login/spinner.

#### A.1 Configuração do Contexto

```python
context_config = {
    "viewport": {"width": 1920, "height": 1080},
    "device_scale_factor": 1.0,
    "user_agent": "Mozilla/5.0...",
    "locale": "pt-BR",
    # OTIMIZAÇÃO DE RELOAD: Ignorar erros de HTTPS e manter cache
    "ignore_https_errors": True, 
    "bypass_csp": True 
}

# Usar user_data_dir é CRÍTICO para a estratégia de "reload_url":
# Isso mantém o cache de assets (JS/CSS do PowerBI) em disco,
# fazendo com que o reload baixe apenas os dados (JSON), não a aplicação inteira.
browser_context = await browser.new_context(
    **context_config,
    storage_state="session.json"
)
```

#### A.2 Estratégia de Espera Simplificada

**Não usar loops de estabilidade visual.** Usar espera composta pragmática:

```python
async def open_and_stabilize(page, url, delay_ms=4000):
    """
    Estratégia simplificada de estabilização:
    1. networkidle (garante requisições principais terminaram)
    2. delay fixo generoso
    3. state check único
    """
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except TimeoutError:
        # networkidle pode falhar em long polling - continuar mesmo assim
        pass
    
    # Delay fixo: suficiente para maioria dos dashboards
    await page.wait_for_timeout(delay_ms)
    
    # Screenshot + state check
    img = await page.screenshot(type="png", full_page=False)
    
    state = await classify_screen_state(img)
    
    return img, state
```

**Delays configuráveis por provider:**
```python
PROVIDER_DELAYS = {
    "powerbi": 4000,      # Power BI renderiza rápido
    "tableau": 6000,      # Tableau pode ser mais lento
    "looker": 3000,
    "default": 5000
}
```

#### A.3 Classificação de Estado (State Check)

Usar modelo rápido (Gemini Flash) para classificar em **uma única chamada**:

```python
async def classify_screen_state(img) -> dict:
    """
    Retorna:
    {
        "state": "ok" | "login_required" | "access_denied" | 
                 "error_screen" | "empty_content" | "spinner_infinite",
        "confidence": 0.0-1.0,
        "reason": "descrição breve"
    }
    """
    prompt = """
Classifique o estado desta tela de dashboard:

**ok**: Dashboard carregado e visível com conteúdo
**login_required**: Tela de login/autenticação
**access_denied**: Erro de permissão/acesso negado
**error_screen**: Erro técnico (500, timeout, etc)
**empty_content**: Página vazia ou sem dados
**spinner_infinite**: Loading infinito (spinner/progress sem conteúdo)

Retorne JSON:
{
    "state": "...",
    "confidence": 0.95,
    "reason": "breve justificativa"
}

Se tiver dúvida entre 'ok' e outro estado, prefira 'ok'.
"""
    
    response = await gemini_flash.generate(prompt, img)
    return parse_json(response)
```

**Decisão fail-fast:** Se `state != "ok"` e `confidence > 0.7`, abortar imediatamente com erro tipificado.

---

### 3.2 Estágio B: Descoberta de Navegação (The Scout)

**Objetivo:** Identificar elementos de navegação visualmente, sem depender de DOM.

#### B.1 Detecção de Padrões de Navegação

```python
async def discover_navigation(img) -> dict:
    """
    Detecta tipo de navegação e elementos clicáveis.
    
    Retorna:
    {
        "nav_type": "bottom_tabs" | "left_list" | "top_tabs" | 
                    "overflow_menu" | "hamburger" | "none",
        "visible_targets": [
            {
                "label": "Financeiro",
                "bbox_norm": [0.10, 0.92, 0.22, 0.98],  # xmin, ymin, xmax, ymax (0-1)
                "confidence": 0.95
            },
            ...
        ],
        "overflow_trigger": {  # opcional
            "bbox_norm": [...],
            "type": "three_dots" | "hamburger" | "chevron"
        }
    }
    """
    
    prompt = """
Analise esta tela de dashboard e identifique a navegação entre páginas/abas.

PADRÕES COMUNS:
- bottom_tabs: abas na parte inferior
- left_list: lista/menu lateral esquerdo
- top_tabs: abas no topo
- overflow_menu: botão "..." ou "≡" que abre menu
- hamburger: menu hambúrguer (☰)
- none: sem navegação visível

Para cada elemento de navegação encontrado, forneça:
- label: texto visível no botão/aba
- bbox_norm: coordenadas normalizadas [xmin, ymin, xmax, ymax] entre 0 e 1
- confidence: confiança de que é um elemento de navegação

IMPORTANTE:
- Ignore filtros, slicers, botões de ação (exportar, atualizar)
- Foque apenas em elementos que parecem mudar de página/aba
- Se não tiver certeza, inclua mesmo assim (falso positivo é ok)

Retorne JSON válido.
"""
    
    response = await gemini_flash.generate(prompt, img)
    return parse_json(response)
```

#### B.2 Tratamento de Overflow/Hambúrguer

Se `overflow_trigger` estiver presente:

```python
async def resolve_overflow_navigation(page, nav_data):
    """
    Expande menu overflow e redetecta targets.
    """
    if not nav_data.get("overflow_trigger"):
        return nav_data
    
    trigger_bbox = nav_data["overflow_trigger"]["bbox_norm"]
    
    # Screenshot antes
    before = await page.screenshot()
    
    # Clicar no trigger
    await click_at_bbox(page, trigger_bbox)
    await page.wait_for_timeout(1500)  # espera menu abrir
    
    # Screenshot depois
    after = await page.screenshot()
    
    # Verificar se algo mudou (menu abriu)
    if not visual_diff_significant(before, after):
        # Falhou em abrir - retornar navegação original
        return nav_data
    
    # Redetectar com menu aberto
    expanded_nav = await discover_navigation(after)
    expanded_nav["menu_opened"] = True
    
    return expanded_nav
```

**Estratégia de fallback:**
- Se `nav_type = "none"` → tentar prompt alternativo mais permissivo
- Se ainda assim `none` → tratar como dashboard de página única (catalogar apenas estado atual)

---

### 3.3 Estágio C: Exploração e Validação de Mudança (The Explorer)

**Objetivo:** Clicar em targets detectados e validar mudanças de página, evitando duplicatas.

#### C.1 Estratégia de Reset (Anti-Deriva)

**Padrão recomendado:** `reset_strategy = "reload_url"`

Para cada target explorado, voltar ao estado base recarregando a URL:

```python
async def explore_dashboard(page, url, nav_data, reset_strategy="reload_url"):
    """
    Orquestrador principal de exploração.
    """
    targets = nav_data["visible_targets"]
    results = []
    seen_hashes = set()
    
    for i, target in enumerate(targets, start=1):
        # Reset para estado base
        if reset_strategy == "reload_url":
            base_img, state = await open_and_stabilize(page, url)
            if state["state"] != "ok":
                log_warning(f"Reset failed: {state}")
                continue
        
        # Capturar estado antes
        before_img = await page.screenshot()
        
        # Tentar clicar
        click_result = await attempt_click(page, target)
        
        if not click_result["success"]:
            results.append(create_failed_record(i, target, click_result))
            continue
        
        # Esperar após clique
        await page.wait_for_timeout(3000)
        
        # Capturar estado depois
        after_img = await page.screenshot()
        
        # Validar mudança
        changed, metrics = verify_page_change(
            before_img, 
            after_img, 
            nav_type=nav_data["nav_type"]
        )
        
        if not changed:
            results.append(create_no_change_record(i, target, metrics))
            continue
        
        # Verificar duplicata
        page_hash = compute_content_hash(after_img, nav_data["nav_type"])
        
        if page_hash in seen_hashes:
            results.append(create_duplicate_record(i, target, metrics, page_hash))
            continue
        
        seen_hashes.add(page_hash)
        
        # Página válida - adicionar aos resultados
        results.append(create_valid_page_record(i, target, after_img, metrics))
    
    return results
```

**Estratégias alternativas** (configuráveis, mas não padrão):
- `return_home`: detectar e clicar em botão "Home"/"Visão Geral"
- `back_button`: detectar e usar botão "Voltar" (útil para drillthrough)

#### C.2 Clique Robusto com Fallback Simples

```python
async def attempt_click(page, target, max_attempts=2):
    """
    Tenta clicar no target com fallback de posição.
    """
    bbox = target["bbox_norm"]
    viewport = page.viewport_size
    
    # Converter bbox normalizado para pixels
    x_min = int(bbox[0] * viewport["width"])
    y_min = int(bbox[1] * viewport["height"])
    x_max = int(bbox[2] * viewport["width"])
    y_max = int(bbox[3] * viewport["height"])
    
    # Pontos para tentar (centro, depois cantos)
    points = [
        (x_min + (x_max - x_min) * 0.5, y_min + (y_max - y_min) * 0.5),  # centro
        (x_min + (x_max - x_min) * 0.4, y_min + (y_max - y_min) * 0.5),  # centro-esquerda
    ]
    
    for attempt, (x, y) in enumerate(points[:max_attempts], 1):
        try:
            await page.mouse.click(x, y)
            return {"success": True, "attempts": attempt, "coords": (x, y)}
        except Exception as e:
            if attempt == max_attempts:
                return {
                    "success": False, 
                    "attempts": attempt,
                    "error": str(e),
                    "coords": (x, y)
                }
            await page.wait_for_timeout(500)
    
    return {"success": False, "attempts": max_attempts}
```

**Scroll de navegação** (se necessário):

```python
# Se target estiver fora da viewport (lista lateral scrollável)
if y_max > viewport["height"]:
    nav_region = estimate_nav_region(nav_data["nav_type"])
    await scroll_region(page, nav_region, target_y=y_min)
    await page.wait_for_timeout(800)
```

#### C.3 Validação de Mudança (Regra "2 de 3")

Comparar screenshots `before` e `after` usando três sinais independentes:

```python
def verify_page_change(img_before, img_after, nav_type, thresholds=None):
    """
    Validação multi-sinal: precisa de 2 de 3 votos para confirmar mudança.
    
    Retorna: (changed: bool, metrics: dict)
    """
    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS[nav_type]
    
    votes = 0
    metrics = {}
    
    # Sinal 1: Global pHash (tela completa)
    hash_before_global = phash(img_before)
    hash_after_global = phash(img_after)
    global_diff = hash_before_global - hash_after_global
    
    metrics["global_phash_diff"] = global_diff
    if global_diff > thresholds["global_phash"]:
        votes += 1
    
    # Sinal 2: Content pHash (ROI sem navegação)
    roi_params = ROI_PRESETS[nav_type]
    roi_before = crop_image(img_before, roi_params)
    roi_after = crop_image(img_after, roi_params)
    
    hash_before_content = phash(roi_before)
    hash_after_content = phash(roi_after)
    content_diff = hash_before_content - hash_after_content
    
    metrics["content_phash_diff"] = content_diff
    if content_diff > thresholds["content_phash"]:
        votes += 1
    
    # Sinal 3: Pixel diff low-res (ROI)
    thumb_before = cv2.resize(roi_before, (64, 64))
    thumb_after = cv2.resize(roi_after, (64, 64))
    pixel_diff = np.mean(np.abs(thumb_before - thumb_after)) / 255.0
    
    metrics["pixel_diff_percent"] = pixel_diff
    if pixel_diff > thresholds["pixel_diff"]:
        votes += 1
    
    metrics["votes"] = votes
    changed = votes >= 2
    
    return changed, metrics
```

**ROI Presets por tipo de navegação:**

```python
ROI_PRESETS = {
    "bottom_tabs": {
        "top": 0.0,
        "bottom": 0.10,    # exclui barra inferior
        "left": 0.0,
        "right": 0.0
    },
    "left_list": {
        "top": 0.0,
        "bottom": 0.0,
        "left": 0.20,      # exclui menu lateral
        "right": 0.0
    },
    "top_tabs": {
        "top": 0.08,       # exclui barra superior
        "bottom": 0.0,
        "left": 0.0,
        "right": 0.0
    },
    "overflow_menu": {
        "top": 0.05,
        "bottom": 0.05,
        "left": 0.05,
        "right": 0.05
    },
    "hamburger": {
        "top": 0.0,
        "bottom": 0.0,
        "left": 0.15,
        "right": 0.0
    },
    "none": {
        "top": 0.0,
        "bottom": 0.0,
        "left": 0.0,
        "right": 0.0
    }
}
```

**Thresholds por provider e nav_type:**

```python
DEFAULT_THRESHOLDS = {
    "bottom_tabs": {
        "global_phash": 6,
        "content_phash": 8,
        "pixel_diff": 0.03
    },
    "left_list": {
        "global_phash": 5,
        "content_phash": 7,
        "pixel_diff": 0.025
    },
    "top_tabs": {
        "global_phash": 6,
        "content_phash": 8,
        "pixel_diff": 0.03
    },
    "overflow_menu": {
        "global_phash": 7,
        "content_phash": 9,
        "pixel_diff": 0.04
    },
    "hamburger": {
        "global_phash": 6,
        "content_phash": 8,
        "pixel_diff": 0.03
    },
    "none": {
        "global_phash": 5,
        "content_phash": 5,
        "pixel_diff": 0.02
    }
}
```

#### C.4 Deduplicação por Hash de Conteúdo

```python
def compute_content_hash(img, nav_type):
    """
    Hash do ROI de conteúdo para detectar duplicatas.
    """
    roi_params = ROI_PRESETS[nav_type]
    roi = crop_image(img, roi_params)
    return str(phash(roi))

def is_duplicate(page_hash, seen_hashes, similarity_threshold=2):
    """
    Verifica se hash é similar a algum já visto.
    """
    for seen in seen_hashes:
        diff = hamming_distance(page_hash, seen)
        if diff <= similarity_threshold:
            return True
    return False
```

#### C.5 Tipificação de Status de Target

Não usar termo genérico `broken_link`. Usar status descritivo:

```python
TARGET_STATUS = {
    "clicked_changed": "Clique bem-sucedido com mudança de página confirmada",
    "clicked_no_change": "Clique executado mas página não mudou",
    "click_failed": "Falha ao executar clique (elemento não clicável)",
    "timeout_after_click": "Timeout após clique (página não carregou)",
    "duplicate_page": "Página idêntica a outra já catalogada",
    "state_error_after_click": "Página resultante em estado de erro",
    "reset_failed": "Falha ao retornar ao estado base"
}
```

---

### 3.4 Estágio D: Catalogação Macro (The Analyst)

**Objetivo:** Extrair estrutura visual e classificação semântica de alto nível, sem focar em valores exatos.

#### D.1 Prompt de Análise Focado em Macro

```python
async def analyze_page_macro(img, target_label=None):
    """
    Análise macro com modelo Pro (Gemini 1.5 Pro ou GPT-4o).
    """
    
    prompt = """
Analise esta tela de dashboard de Business Intelligence e extraia informações ESTRUTURAIS (não valores exatos).

FOCO DA ANÁLISE:

1. **Identificação da Página**
   - Título ou nome visível (se houver)
   - Se não houver título claro, descreva o tema geral

2. **Estrutura Visual** (tipos de visualizações presentes)
   - Gráficos: barras, linhas, pizza, área, dispersão, etc.
   - Tabelas/matrizes
   - Cartões de KPI/métricas
   - Mapas geográficos
   - Treemaps, funis, etc.
   
   Para cada tipo, indique quantidade aproximada (ex: "3 gráficos de barra")

3. **Elementos de Controle Visíveis**
   - Filtros/slicers (apenas NOMES, não valores selecionados)
   - Seletores de data
   - Dropdowns
   
4. **Classificação Semântica**
   - Domínio de negócio: Financeiro, Vendas, Operações, RH, Marketing, TI, etc.
   - Público-alvo provável: Executivo, Gerencial, Operacional, Analítico
   - Perguntas de negócio que esta página provavelmente responde (2-3 exemplos)

5. **Qualidade e Legibilidade**
   - Legibilidade geral: alta, média, baixa
   - Elementos ilegíveis ou cortados (se houver)

IMPORTANTE - NÃO EXTRAIR:
- Valores numéricos exatos de KPIs
- Conteúdo completo de tabelas
- Textos longos ou descrições detalhadas
- Dados de séries temporais específicos

Se algo não estiver legível ou claro, indique explicitamente.

Retorne JSON estritamente neste formato:

{
  "identificacao": {
    "titulo_visivel": "string ou null",
    "tema_geral": "string"
  },
  "estrutura_visual": {
    "graficos": [
      {"tipo": "barras", "quantidade": 2},
      {"tipo": "linha", "quantidade": 1}
    ],
    "tabelas": {"presente": true, "quantidade": 1},
    "cartoes_kpi": {"presente": true, "quantidade": 4},
    "mapas": {"presente": false},
    "outros": []
  },
  "controles": {
    "filtros_visiveis": ["Nome do Filtro 1", "Nome do Filtro 2"],
    "seletores_data": true,
    "outros_controles": []
  },
  "classificacao": {
    "dominio_negocio": "Financeiro | Vendas | Operações | ...",
    "publico_alvo": "Executivo | Gerencial | Operacional | Analítico",
    "perguntas_respondiveis": [
      "Pergunta de negócio 1",
      "Pergunta de negócio 2"
    ]
  },
  "qualidade": {
    "legibilidade": "alta | média | baixa",
    "elementos_ilegiveis": [],
    "observacoes": "string opcional"
  }
}
"""

    if target_label:
        prompt += f"\n\nCONTEXTO: Esta página foi acessada clicando no botão/aba '{target_label}'.\n"
    
    response = await gemini_pro.generate(prompt, img)
    return parse_json_safe(response)
```

#### D.2 Separação de Fatos e Interpretação

O schema JSON já separa naturalmente:

**Factual** (observável diretamente):
- `estrutura_visual`: tipos e quantidades de visuais
- `controles.filtros_visiveis`: nomes de filtros
- `qualidade.legibilidade`: assessment visual
- `identificacao.titulo_visivel`: texto exato (se legível)

**Interpretação** (inferido pelo modelo):
- `classificacao.dominio_negocio`: inferência semântica
- `classificacao.publico_alvo`: inferência de uso
- `classificacao.perguntas_respondiveis`: hipóteses de propósito

**Incertezas explícitas:**
```python
# Se modelo não tiver certeza:
{
  "identificacao": {
    "titulo_visivel": null,
    "tema_geral": "Análise de vendas (título não legível)"
  },
  "qualidade": {
    "elementos_ilegiveis": ["Rótulos do eixo X do gráfico de barras"],
    "observacoes": "Parte inferior da tela cortada/não renderizada"
  }
}
```

#### D.3 Redaction para Publicação (Opcional)

**Dois modos de operação:**

1. **Modo Interno** (padrão para execução):
   - Salvar imagens originais
   - Análise trabalha com imagens não modificadas
   - Redaction não é aplicada

2. **Modo Publicação** (para exportar catálogo):
   - Aplicar redaction antes de persistir
   - Nunca incluir imagens originais no pacote exportado

**Redaction simplificada:**

```python
async def apply_simple_redaction(img):
    """
    Redaction básica via OCR + blur de padrões sensíveis.
    """
    # OCR leve apenas para detectar padrões
    text_regions = await ocr_detect_patterns(img, patterns=[
        r'\b[\w\.-]+@[\w\.-]+\.\w+\b',  # emails
        r'\b\d{3}\.\d{3}\.\d{3}-\d{2}\b',  # CPF
        r'\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b',  # CNPJ
    ])
    
    # Aplicar blur gaussiano nas regiões detectadas
    for region in text_regions:
        img = blur_region(img, region["bbox"], kernel_size=15)
    
    return img
```

**Alternativa sem OCR** (instrução ao LLM):

```python
# No prompt do Analyst, adicionar:
"""
PRIVACIDADE:
- Não transcreva emails, CPFs, CNPJs, ou outros dados pessoais
- Não transcreva valores numéricos sensíveis (receitas, margens, salários)
- Foque em estrutura, tipos de visual, e categorias gerais
"""
```

---

## 4. Schema de Dados (Output JSON v2)

Um arquivo JSON por dashboard, validado com Pydantic.

```json
{
  "meta_info": {
    "run_id": "20260113T150000Z_abc123def",
    "url": "https://app.powerbi.com/...",
    "provider": "powerbi",
    "execution_timestamp": "2026-01-13T15:00:00Z",
    "execution_duration_seconds": 87.3,
    "status_execucao": "sucesso",
    "config": {
      "reset_strategy": "reload_url",
      "delay_ms": 4000,
      "viewport": {
        "width": 1920,
        "height": 1080,
        "device_scale_factor": 1.0
      }
    },
    "errors": [],
    "warnings": []
  },
  
  "initial_state": {
    "state_check": {
      "state": "ok",
      "confidence": 0.98,
      "reason": "Dashboard loaded with visible content"
    },
    "screenshot_path": "runs/20260113T150000Z_abc123def/screenshots/00_initial.png"
  },
  
  "navigation": {
    "nav_type": "bottom_tabs",
    "menu_opened": false,
    "targets_detected": 6,
    "overflow_trigger_present": false,
    "raw_detection": {
      "visible_targets": [
        {
          "label": "Visão Geral",
          "bbox_norm": [0.05, 0.92, 0.15, 0.98],
          "confidence": 0.95
        },
        {
          "label": "Financeiro",
          "bbox_norm": [0.16, 0.92, 0.26, 0.98],
          "confidence": 0.93
        }
      ]
    }
  },
  
  "paginas": [
    {
      "id_sequencial": 1,
      
      "target": {
        "label": "Financeiro",
        "bbox_norm": [0.16, 0.92, 0.26, 0.98],
        "click_coords": [403, 1013],
        "status": "clicked_changed",
        "attempts": 1,
        "reset_performed": true
      },
      
      "validation": {
        "changed": true,
        "votes": 3,
        "thresholds_used": {
          "global_phash": 6,
          "content_phash": 8,
          "pixel_diff": 0.03
        },
        "metrics": {
          "global_phash_diff": 12,
          "content_phash_diff": 15,
          "pixel_diff_percent": 0.047
        },
        "roi_used": {
          "type": "bottom_tabs",
          "params": {"top": 0.0, "bottom": 0.10, "left": 0.0, "right": 0.0}
        },
        "content_hash": "a3f5c8d9e2b1a456",
        "is_duplicate": false
      },
      
      "analise_macro": {
        "identificacao": {
          "titulo_visivel": "Demonstrativo de Resultados 2024",
          "tema_geral": "Análise financeira com DRE e indicadores"
        },
        "estrutura_visual": {
          "graficos": [
            {"tipo": "linha", "quantidade": 2},
            {"tipo": "barras", "quantidade": 1}
          ],
          "tabelas": {"presente": true, "quantidade": 1},
          "cartoes_kpi": {"presente": true, "quantidade": 5},
          "mapas": {"presente": false},
          "outros": []
        },
        "controles": {
          "filtros_visiveis": ["Ano Fiscal", "Centro de Custo", "Categoria"],
          "seletores_data": true,
          "outros_controles": ["Botão de drill-down"]
        },
        "classificacao": {
          "dominio_negocio": "Financeiro",
          "publico_alvo": "Gerencial",
          "perguntas_respondiveis": [
            "Como está a evolução do EBITDA ao longo do ano?",
            "Qual a distribuição de custos por centro?",
            "A margem está dentro da meta?"
          ]
        },
        "qualidade": {
          "legibilidade": "alta",
          "elementos_ilegiveis": [],
          "observacoes": null
        }
      },
      
      "arquivos": {
        "screenshot_original_path": "runs/20260113T150000Z_abc123def/screenshots/01_financeiro_original.png",
        "screenshot_redacted_path": null
      },
      
      "timing": {
        "click_timestamp": "2026-01-13T15:01:23Z",
        "stabilization_duration_ms": 3200
      }
    },
    
    {
      "id_sequencial": 2,
      
      "target": {
        "label": "Vendas",
        "bbox_norm": [0.27, 0.92, 0.37, 0.98],
        "click_coords": [620, 1013],
        "status": "clicked_no_change",
        "attempts": 1,
        "reset_performed": true
      },
      
      "validation": {
        "changed": false,
        "votes": 0,
        "metrics": {
          "global_phash_diff": 2,
          "content_phash_diff": 1,
          "pixel_diff_percent": 0.008
        }
      },
      
      "analise_macro": null,
      "arquivos": null,
      
      "observacao": "Clique não resultou em mudança de página - possível botão inativo ou highlight apenas"
    },
    
    {
      "id_sequencial": 3,
      
      "target": {
        "label": "Operações",
        "bbox_norm": [0.38, 0.92, 0.48, 0.98],
        "click_coords": [827, 1013],
        "status": "duplicate_page",
        "attempts": 1,
        "reset_performed": true
      },
      
      "validation": {
        "changed": true,
        "votes": 2,
        "metrics": {
          "global_phash_diff": 8,
          "content_phash_diff": 9,
          "pixel_diff_percent": 0.035
        },
        "content_hash": "a3f5c8d9e2b1a456",
        "is_duplicate": true,
        "duplicate_of_page_id": 1
      },
      
      "observacao": "Página idêntica à página 1 (Financeiro) - possível alias ou visualização duplicada"
    }
  ],
  
  "summary": {
    "total_targets_detected": 6,
    "total_targets_explored": 6,
    "pages_cataloged": 3,
    "unique_pages": 2,
    "failed_clicks": 0,
    "duplicates": 1,
    "no_change_clicks": 1
  }
}
```

### 4.1 Modelos Pydantic

```python
from pydantic import BaseModel, Field, HttpUrl
from typing import List, Optional, Literal
from datetime import datetime
from pydantic import field_validator

class ViewportConfig(BaseModel):
    width: int = 1920
    height: int = 1080
    device_scale_factor: float = 1.0

class ExecutionConfig(BaseModel):
    reset_strategy: Literal["reload_url", "return_home", "back_button"] = "reload_url"
    delay_ms: int = 4000
    viewport: ViewportConfig

class StateCheck(BaseModel):
    state: Literal["ok", "login_required", "access_denied", "error_screen", "empty_content", "spinner_infinite"]
    confidence: float = Field(ge=0, le=1)
    reason: str

class InitialState(BaseModel):
    state_check: StateCheck
    screenshot_path: str

class BBoxNorm(BaseModel):
    """Bounding box normalizado [xmin, ymin, xmax, ymax]"""
    coords: List[float] = Field(min_length=4, max_length=4)
    
    @field_validator('coords')
    @classmethod
    def validate_geometry(cls, v):
        # Garante que xmin < xmax e ymin < ymax
        if v[0] >= v[2] or v[1] >= v[3]:
            raise ValueError(f"Geometria inválida (min >= max): {v}")
        # Garante que está normalizado entre 0 e 1
        if not all(0.0 <= x <= 1.0 for x in v):
            raise ValueError(f"Coordenadas fora da normalização 0-1: {v}")
        return v

    @property
    def xmin(self) -> float: 
        return self.coords[0]
    
    @property
    def xmin(self) -> float:
        return self.coords[0]
    
    @property
    def ymin(self) -> float:
        return self.coords[1]
    
    @property
    def xmax(self) -> float:
        return self.coords[2]
    
    @property
    def ymax(self) -> float:
        return self.coords[3]

class NavigationTarget(BaseModel):
    label: str
    bbox_norm: List[float] = Field(min_length=4, max_length=4)
    confidence: float = Field(ge=0, le=1)

class NavigationDiscovery(BaseModel):
    nav_type: Literal["bottom_tabs", "left_list", "top_tabs", "overflow_menu", "hamburger", "none"]
    menu_opened: bool = False
    targets_detected: int
    overflow_trigger_present: bool = False
    raw_detection: dict

class TargetExecution(BaseModel):
    label: str
    bbox_norm: List[float]
    click_coords: List[int]
    status: Literal[
        "clicked_changed",
        "clicked_no_change",
        "click_failed",
        "timeout_after_click",
        "duplicate_page",
        "state_error_after_click",
        "reset_failed"
    ]
    attempts: int
    reset_performed: bool

class ValidationMetrics(BaseModel):
    global_phash_diff: int
    content_phash_diff: int
    pixel_diff_percent: float

class ValidationResult(BaseModel):
    changed: bool
    votes: int
    thresholds_used: Optional[dict] = None
    metrics: ValidationMetrics
    roi_used: Optional[dict] = None
    content_hash: Optional[str] = None
    is_duplicate: bool = False
    duplicate_of_page_id: Optional[int] = None

class VisualStructure(BaseModel):
    graficos: List[dict] = []
    tabelas: dict = {"presente": False, "quantidade": 0}
    cartoes_kpi: dict = {"presente": False, "quantidade": 0}
    mapas: dict = {"presente": False}
    outros: List[dict] = []

class Controles(BaseModel):
    filtros_visiveis: List[str] = []
    seletores_data: bool = False
    outros_controles: List[str] = []

class Classificacao(BaseModel):
    dominio_negocio: str
    publico_alvo: str
    perguntas_respondiveis: List[str] = []

class Qualidade(BaseModel):
    legibilidade: Literal["alta", "média", "baixa"]
    elementos_ilegiveis: List[str] = []
    observacoes: Optional[str] = None

class Identificacao(BaseModel):
    titulo_visivel: Optional[str] = None
    tema_geral: str

class AnaliseMacro(BaseModel):
    identificacao: Identificacao
    estrutura_visual: VisualStructure
    controles: Controles
    classificacao: Classificacao
    qualidade: Qualidade

class Arquivos(BaseModel):
    screenshot_original_path: Optional[str] = None
    screenshot_redacted_path: Optional[str] = None

class Timing(BaseModel):
    click_timestamp: datetime
    stabilization_duration_ms: int

class PageRecord(BaseModel):
    id_sequencial: int
    target: TargetExecution
    validation: ValidationResult
    analise_macro: Optional[AnaliseMacro] = None
    arquivos: Optional[Arquivos] = None
    timing: Optional[Timing] = None
    observacao: Optional[str] = None

class Summary(BaseModel):
    total_targets_detected: int
    total_targets_explored: int
    pages_cataloged: int
    unique_pages: int
    failed_clicks: int
    duplicates: int
    no_change_clicks: int

class MetaInfo(BaseModel):
    run_id: str
    url: HttpUrl
    provider: str
    execution_timestamp: datetime
    execution_duration_seconds: float
    status_execucao: Literal["sucesso", "parcial", "falha"]
    config: ExecutionConfig
    errors: List[str] = []
    warnings: List[str] = []

class DashboardCatalog(BaseModel):
    meta_info: MetaInfo
    initial_state: InitialState
    navigation: NavigationDiscovery
    paginas: List[PageRecord]
    summary: Summary
    
    class Config:
        json_schema_extra = {
            "example": {
                "meta_info": {
                    "run_id": "20260113T150000Z_abc123",
                    "url": "https://app.powerbi.com/view?r=...",
                    "provider": "powerbi",
                    "execution_timestamp": "2026-01-13T15:00:00Z",
                    "execution_duration_seconds": 87.3,
                    "status_execucao": "sucesso"
                }
            }
        }
```

---

## 5. Roadmap de Implementação

### Fase 1: Fundação Robusta (2 semanas)

**Objetivo:** Configuração básica + estabilização + state check funcionando.

**Entregas:**
- ✅ Setup Playwright com `user_data_dir` e viewport fixo
- ✅ Função `open_and_stabilize()` com networkidle + delay configurável
- ✅ State check com Gemini Flash (ok/login/error/etc)
- ✅ Logging estruturado com `run_id`
- ✅ Testes: abrir 10 URLs diferentes, salvar screenshot inicial ou retornar erro tipificado

**Critério de sucesso:** 
- 90%+ de URLs válidos retornam `state=ok`
- Erros (login/access denied) são corretamente identificados

---

### Fase 2: Navegador Visual (3 semanas)

**Objetivo:** Descoberta de navegação + exploração com validação robusta.

**Entregas:**

**Semana 1:**
- ✅ Scout: prompt + parser JSON para detecção de `nav_type` e targets
- ✅ Tratamento de overflow/hambúrguer (B.2)
- ✅ Testes: 10 dashboards diversos, validar detecção manual

**Semana 2:**
- ✅ Clique robusto com fallback de coordenadas
- ✅ Validação "2 de 3" com ROI por nav_type
- ✅ Função `verify_page_change()` com métricas completas
- ✅ Testes: confirmar que mudanças reais são detectadas e cliques vazios são rejeitados

**Semana 3:**
- ✅ Orquestrador de exploração com reset (reload_url)
- ✅ Deduplicação por content_hash
- ✅ Tipificação de status de target (clicked_changed, no_change, duplicate, etc)
- ✅ Testes end-to-end: catalogar 5 dashboards completos

**Critério de sucesso:**
- Para dashboard típico (6-8 páginas), sistema identifica 80%+ das páginas válidas
- Taxa de falsos positivos (cliques que não mudam nada) < 20%
- Duplicatas óbvias são filtradas

---

### Fase 3: Catalogador Analítico (2 semanas)

**Objetivo:** Análise macro + schema completo + persistência.

**Entregas:**

**Semana 1:**
- ✅ Prompt de análise macro com Gemini Pro
- ✅ Parser JSON para schema `AnaliseMacro`
- ✅ Integração no pipeline: chamar Analyst apenas para páginas válidas
- ✅ Validação Pydantic de todo o output

**Semana 2:**
- ✅ Geração de JSON completo por dashboard
- ✅ Estrutura de pastas: `runs/{run_id}/screenshots/` e `catalog.json`
- ✅ Summary statistics
- ✅ Documentação de uso

**Critério de sucesso:**
- JSON válido gerado para 100% dos runs bem-sucedidos
- Análise macro identifica corretamente domínio de negócio em 80%+ dos casos
- Estrutura visual (tipos de gráficos) é extraída com precisão razoável

---

### Fase 4: Escala e Refinamento (contínua)

**Objetivo:** Otimizações para produção + features avançadas.

**Entregas:**

**Sprint 1 (1-2 semanas):**
- ✅ Paralelização: múltiplos workers com contextos isolados
- ✅ Rate limiting e retry policies
- ✅ Resumo de runs: estatísticas agregadas por provider

**Sprint 2 (2-3 semanas):**
- ✅ Redaction robusto (OCR + blur ou alternativa sem OCR)
- ✅ Modo publicação vs modo interno
- ✅ Detecção de drillthrough (botão "Voltar")

**Sprint 3 (2-3 semanas):**
- ✅ Deduplicação semântica entre dashboards (embeddings visuais)
- ✅ UI simples para visualizar catálogo (web app com Flask/FastAPI)
- ✅ Exportação para formatos alternativos (Parquet, SQLite)

**Sprint 4 (1-2 semanas):**
- ✅ Suporte a outros providers (Tableau, Looker)
- ✅ Ajuste de thresholds e ROIs por provider
- ✅ Testes de carga: 100+ dashboards em paralelo

---

## 6. Estimativas de Performance e Custo

### 6.1 Tempo de Execução

**Dashboard típico (8 páginas navegáveis):**

```
Estágio A (initial state):
  - goto + networkidle: 3-5s
  - delay: 4s
  - state check (Gemini Flash): 1-2s
  Subtotal: ~7s

Estágio B (scout):
  - detect navigation (Gemini Flash): 1-2s
  - overflow expansion (se necessário): +3s
  Subtotal: ~2s (sem overflow) a ~5s (com overflow)

Estágio C (explorer) - 8 targets:
  Para cada target:
    - reset (goto + wait): 7s
    - click + wait: 3s
    - validation (local): <1s
  Subtotal: 8 × 10s = 80s

Estágio D (analyst) - páginas válidas (assumir 6):
  - análise macro (Gemini Pro): 2-3s por página
  Subtotal: 6 × 2.5s = 15s

TOTAL: ~7 + 2 + 80 + 15 = **104 segundos (~1.7 min)**
```

**Para 100 dashboards:**
- Sequencial: ~170 minutos (2h50min)
- Com 5 workers paralelos: ~34 minutos
- Com 10 workers paralelos: ~17 minutos

### 6.2 Custos de API

**Por dashboard (8 páginas, 6 válidas):**

```
Gemini Flash (state checks + scout):
  - 1 state check initial: $0.001
  - 1 scout call: $0.001
  - 8 validations pós-click (state check rápido): $0.008
  Subtotal Flash: ~$0.01

Gemini Pro (análise macro):
  - 6 páginas × $0.03/call = $0.18
  Subtotal Pro: ~$0.18

TOTAL por dashboard: ~$0.19
```

**Para escala:**
- 100 dashboards: ~$19
- 1.000 dashboards: ~$190
- 10.000 dashboards: ~$1.900

**Otimizações possíveis:**
- Caching de análises de páginas duplicadas entre dashboards: economia de 20-30%
- Usar modelos locais (LLaVA, CogVLM) para state checks: economia de 50% em Flash
- Batch requests quando API permitir

### 6.3 Requisitos de Infraestrutura

**Para execução local/VM:**
- CPU: 4+ cores (paralelização)
- RAM: 8GB+ (Playwright + múltiplos contextos)
- Disco: ~100MB por dashboard catalogado (screenshots + JSON)
- Rede: baixa latência para APIs de LLM

**Para 1.000 dashboards:**
- Disco: ~100GB
- Execução com 10 workers: ~3 horas
- Custo API: ~$190

---

## 7. Riscos e Mitigações

### 7.1 Riscos Técnicos

| Risco | Probabilidade | Impacto | Mitigação |
|-------|---------------|---------|-----------|
| **Spinner/loading infinito** | Média | Alto | Delay fixo + timeout rígido. Se comum, aumentar delay padrão para provider específico |
| **Clique detecta apenas highlight de aba** | Média | Médio | Validação "2 de 3" com ROI que exclui área de navegação |
| **Overflow/hambúrguer esconde páginas** | Média | Médio | Tratamento explícito (B.2). Se comum, fazer sempre mesmo sem detecção |
| **Drillthrough confunde exploração** | Baixa | Médio | Detectar botão "Voltar" após clique. Se presente, marcar como drillthrough e voltar |
| **Duplicatas semânticas não detectadas** | Média | Baixo | Fase 4: clustering por embeddings. Para MVP, aceitar duplicatas |
| **LLM alucina estrutura visual** | Baixa | Baixo | Prompt focado em "apenas visível". Validação humana periódica |
| **SSO/MFA expira** | Alta | Alto | `user_data_dir` + renovação manual periódica. Alertar quando state=login |
| **Rate limit de API** | Baixa | Médio | Exponential backoff + retry. Monitorar uso em tempo real |
| **Power BI detecta automação** | Baixa | Alto | User agent realista + delays humanos + rotação de contextos |

### 7.2 Riscos de Negócio

| Risco | Mitigação |
|-------|-----------|
| **Expectativa de precisão 100%** | Documentar desde o início que é catalogação macro (85-90% precisão esperada) |
| **Dados sensíveis em screenshots** | Modo interno vs publicação. Redaction obrigatória para exportação |
| **Dashboards muito complexos (50+ páginas)** | Timeout configurável. Sugerir recorte/filtro prévio |
| **Custo de API escala rápido** | Caching agressivo + opção de modelos locais para state checks |

### 7.3 Casos de Falha Esperados

**O sistema NÃO vai funcionar bem para:**

1. **Dashboards que exigem interação com filtros para mostrar conteúdo**
   - Ex: painel vazio até selecionar região no slicer
   - Mitigação parcial: detectar slicers e tentar interação básica (Fase 4)

2. **Painéis com autenticação de curta duração (<1h)**
   - Sistema precisa de sessões estáveis
   - Mitigação: execução em janelas de tempo restritas + renovação assistida

3. **Dashboards com navegação não-visual (ex: apenas via URLs)**
   - Scout não consegue detectar
   - Mitigação: permitir input manual de lista de URLs/páginas

4. **Portais com proteção anti-bot agressiva**
   - Playwright pode ser detectado
   - Mitigação: fallback para automação manual assistida

---

## 8. Critérios de Sucesso do MVP

### 8.1 Critérios Técnicos

**Must-have (Fase 1-3):**
- ✅ Abre URL e detecta estado corretamente (ok/login/error) em 90%+ dos casos
- ✅ Identifica navegação (nav_type + targets) em 80%+ dos dashboards
- ✅ Explora páginas com taxa de sucesso 70%+ (páginas válidas catalogadas / targets clicados)
- ✅ Gera JSON válido (Pydantic) para 100% dos runs completos
- ✅ Análise macro identifica domínio de negócio corretamente em 75%+ dos casos

**Nice-to-have (Fase 4):**
- ⭐ Detecta e filtra duplicatas com precisão 80%+
- ⭐ Executa 10+ dashboards em paralelo sem conflitos
- ⭐ Redaction remove dados sensíveis com recall 90%+

### 8.2 Critérios de Produto

**Usabilidade:**
- Executar catalogação de 1 dashboard requer apenas URL como input
- Output JSON é legível e navegável (estrutura clara)
- Erros são reportados com contexto suficiente para debugging

**Performance:**
- Dashboard típico (8 páginas) catalogado em < 2 minutos
- Custo < $0.25 por dashboard

**Cobertura:**
- Funciona com dashboards Power BI padrão (tabs/menu lateral)
- Suporta dashboards com 3-20 páginas
- Taxa de falha catastrófica (crash/timeout total) < 5%
