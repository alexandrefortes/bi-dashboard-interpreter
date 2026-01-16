[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

# bi-dashboard-interpreter

*A focused crawler for BI dashboards (UI-level, non-invasive).*

Este projeto utiliza IA Multimodal (Gemini 2.5) e Automação de Navegador (Playwright) para navegar, capturar e documentar funcionalmente painéis de Business Intelligence (Power BI, etc.) automaticamente.

> **Nota de uso:** Execute apenas com credenciais próprias e em conteúdos cuja captura/armazenamento (prints e metadados) seja permitido pelas políticas do ambiente.

## 🧱 Modularização

O código segue princípios de responsabilidade única:
* **`main.py`**: Orquestrador de entrada (Execução sequencial).
* **`batch_main.py`**: Orquestrador de alta performance (Execução paralela/assíncrona).
* **`cataloger.py`**: Orquestrador do fluxo (Coordena Batedor, Explorador e Analista).
* **`explorer.py`**: Motor de navegação e exploração de páginas (Gerencia cliques e deduplicação).
* **`click_strategy.py`**: Estratégias de clique com retries (Círculos Concêntricos, DOM Fallback).
* **`llm_service.py`**: Integração com Google GenAI (Gemini).
* **`bot_core.py`**: Camada de abstração do Playwright.
* **`config.py`**: Centralização de constantes e ajustes finos.

## 🧪 Dashboards de exemplo (para testes)

* [Financial Performance Dashboard](https://community.fabric.microsoft.com/t5/Themes-Gallery/Financial-Performance-Dashboard/m-p/4901530), por Arbaz_Ahmad (Fabric Community Themes Gallery)
* [Marketing Campaign Analysis Dashboard](https://community.fabric.microsoft.com/t5/Themes-Gallery/Marketing-Campaign-Analysis-Dashboard/td-p/4887536), por visually (Fabric Community Themes Gallery)

**Observação:** os dashboards acima são de terceiros e estão publicados como showcase.

## 🚀 Como rodar

1. **Instale as dependências:**
```bash
pip install -r requirements.txt

```

2. **Configure o ambiente:**
Crie um arquivo `.env` na raiz com sua chave:
```env
GEMINI_API_KEY="sua_chave_aqui"
```


3. **Instale os navegadores:**
```bash
playwright install chromium
```


4. **Execute:**
Gere o arquivo de URLs (via notebook `bi-dashboard-interpreter.ipynb` ou manualmente) e rode:
```bash
python main.py
```

## 🔐 Ambientes com Login (MFA/SSO)

O robô foi desenhado para atuar em colaboração com o humano ("Human-in-the-loop") para operar em ambientes com SSO/MFA com participação do usuário autenticado.

1. Ao iniciar, o robô abre o navegador.
2. Se ele encontrar uma tela de login, o terminal exibirá: **`🛑 TELA DE LOGIN DETECTADA`**.
3. **Sua vez:** Vá até a janela do navegador aberta, digite seu e-mail, senha e aprove o MFA no celular.
4. Assim que o painel carregar, o robô detecta a mudança e retoma a automação sozinho.

> **Dica:** Se após o login a URL mudar para algo não esperado (ex: /home), copie a primeira URL do vetor (urls.json) e cole na barra de endereços do navegador do robô. Ele detectará o carregamento e continuará.

## 🧠 Arquitetura dos Agentes

O projeto opera com 3 "personas" de IA sequenciais:

### 1. The Scout (O Batedor)

* **Função:** Analisar a UI estática.
* **Lógica:** Envia o print da Home para o Gemini Vision. O modelo identifica padrões de navegação:
* *Nativa:* Rodapé do Power BI (ex.: "1 de 5").
* *Customizada:* Abas desenhadas no relatório (Abas superiores, Menu lateral).

* **Saída:** Lista de coordenadas normalizadas (x, y entre 0.0 e 1.0) de onde clicar, independente da resolução.

### 2. The Explorer (O Explorador)

* **Função:** Navegar com resiliência.
* **Lógica Híbrida de Navegação:**
* **Navegação Nativa (Rodapé padrão):** Prioriza **clique direto no DOM** (via seletores CSS/HTML) pela precisão de 100%. Se falhar, recorre ao clique visual.
* **Navegação Customizada (Abas/Botões):** Usa **círculos concêntricos** baseados na visão (Scout). Tenta clicar na coordenada sugerida e, se falhar, expande em espiral até validar a mudança de tela.

### 3. The Analyst (O Analista)

* **Função:** Documentação de Negócio.
* **Lógica:** Analisa apenas as páginas únicas validadas.
* **Saída:** Gera descrições funcionais (título, objetivo, filtros, público-alvo) ignorando dados voláteis (números do dia), focando na estrutura analítica.

### Adendo sobre captura de tela:

1. Acesso inicial ou clique para mudar de página
2. **Estabilização Visual:** Aguarda até que 2 screenshots consecutivas sejam idênticas (perceptual hash)
   - Garante que mapas, gráficos e visuais assíncronos terminem de renderizar
   - Timeout configurável (padrão: 30s navegação, 15s após clique, 5s scroll)
3. Chama `get_full_page_screenshot_bytes()` que:
    ├─ **Detecta scroll container:** Seleciona o elemento de maior área com scroll que ocupe ≥60% do viewport (ignora widgets internos menores)
    ├─ Volta ao topo (scrollTop = 0)
    ├─ Se tem scroll: captura múltiplas vezes com estabilização visual em cada posição
    ├─ Une as capturas
    └─ Volta ao topo novamente
4. Salva a imagem final

---

## 💾 Checkpoints e Resiliência

O sistema possui um mecanismo robusto para evitar perda de dados e reprocessamento desnecessário, ideal para rodar em lote.

### Como funciona
Ao processar uma URL, é criada uma pasta de trabalho temporária (`runs/wip_<hash>`). Se o script for interrompido, ao rodar novamente ele detecta essa pasta e retoma de onde parou:

1.  **Checkpoint do Scout (`scout_checkpoint.json`)**: Salvo após a identificação da navegação.
    *   *Retomada:* Se existir, o robô pula a chamada do LLM e a navegação inicial.
2.  **Checkpoint de Exploração (`exploration_checkpoint.json`)**: Salvo após clicar em todos os botões e coletar as imagens.
    *   *Retomada:* Se existir, o robô **nem abre o navegador**. Ele carrega as imagens do disco e vai direto para a fase de Análise.

### Finalização
Somente após o sucesso de todas as etapas a pasta é renomeada de `wip_<hash>` para o formato final `DATA_Titulo`.

---

## ⚡ Execução em Lote (Alta Performance)

Para processar múltiplas URLs simultaneamente e reduzir o tempo total, utilize o script `batch_main.py`.

### Diferenciais do Modo Batch
*   **Concorrência Controlada:** Processa múltiplos painéis por vez (configurável via `MAX_CONCURRENT_TASKS` em `config.py`).
*   **Navegador Compartilhado:** Abre apenas **uma instância** do Chromium e cria abas isoladas (contextos) para cada painel, economizando RAM por worker.
*   **Logs Contextuais:** O terminal exibe logs com identificadores únicos (ex: `[Worker-1]`, `[Worker-2]`) para facilitar o debug em paralelo.
*   **Segurança (Thread-safe):** Utiliza travas (`asyncio.Lock`) para garantir que o arquivo de histórico (`processed_urls.json`) não seja corrompido.

### Como executar
```bash
python batch_main.py
```

> **Nota:** Certifique-se de que o arquivo `urls.json` esteja populado corretamente.

---

## 📂 Estrutura de Saída

Cada execução cria uma pasta única dentro de `runs/` com o timestamp da execução e o título do painel:

```text
runs/
└── 20260113_213721_Titanic_Dataset/  # ID_Título (sanitizado)
    ├── catalog_Titanic_Dataset.json  # Metadados com título no nome
    └── screenshots/                  # Evidências visuais
        ├── 00_home.png               # Tela inicial
        ├── 01_target.png             # Página 2 (após clique)
        ├── 02_target.png             # Página 3 (após clique)
        └── ...

```

### Exemplo de Saída Real (The Analyst)

Abaixo, um exemplo real de como o agente interpreta uma tela.

**Entrada (Screenshot capturado automaticamente):**

![Exemplo de Dashboard - Media Analytics](hello-world/sample.png)

**Saída (JSON gerado pelo Agente):**

```json
{
  "id": 1,
  "label": "Next Page (1/2)",
  "filename": "01_target.png",
  "analysis": {
    "titulo_painel": "Media Analytics",
    "objetivo_macro": "Monitorar e comparar a performance de campanhas de mídia paga entre diferentes plataformas digitais, analisando a evolução dos principais indicadores em relação ao período anterior.",
    "perguntas_respondidas": [
      "Qual plataforma de mídia digital apresenta o melhor Custo por Clique (CPC) no período selecionado?",
      "Como o investimento (Spend) e o volume de cliques se comparam entre Google, Meta e LinkedIn?",
      "Qual a tendência diária das impressões do mês atual em comparação com o mês anterior para cada plataforma?",
      "Qual foi a variação percentual dos indicadores de performance (Spend, Clicks, CPC) em relação ao mês anterior?"
    ],
    "dominio_negocio": "Marketing",
    "elementos_visuais": "Estrutura de cartões comparativos, um para cada plataforma de mídia. Cada cartão contém um gráfico de linhas para análise de tendência temporal (mês atual vs. anterior) e um conjunto de cartões de KPI para os principais indicadores de performance.",
    "filtros_visiveis": [
      "Mês"
    ],
    "principais_indicadores": [
      "Spend (Investimento)",
      "Clicks (Cliques)",
      "CPC (Custo por Clique)",
      "Impressions (Impressões)"
    ],
    "publico_sugerido": "Analista de Mercado"
  }
}
```

### Exemplos de saída do Scout (Navegação)

Quando o Scout analisa a imagem, ele retorna uma **reflexão (`nav_reflection`)** justificando a decisão, o que ajuda na auditabilidade do processo.

**Caso 1: Nenhuma navegação encontrada**

```json
{
    "nav_reflection": "Seguindo a ordem de prioridade, verifiquei a parte inferior da imagem em busca de um rodapé de navegação nativo do Power BI (barra cinza, contador de páginas, setas). Nenhum rodapé nativo foi encontrado. Em seguida, procurei por abas ou botões de navegação personalizados (no topo, lateral ou rodapé) que mudassem a página inteira. Encontrei vários botões que funcionam como filtros/slicers para os dados da página atual (ex: 'Age Ranges', 'Contains family', 'Sex'), mas nenhum que sirva para navegar entre diferentes páginas do relatório. Como nenhum dos métodos de navegação primários foi identificado, o tipo é 'none'.",
    "nav_type": "none",
    "page_count_visual": null,
    "targets": []
}
```

**Caso 2: Navegação Nativa Detectada**

```json
{
    "nav_reflection": "A análise seguiu a ordem de prioridade definida. Primeiramente, verifiquei a parte inferior da captura de tela e identifiquei um rodapé nativo do Power BI. Este rodapé contém a contagem de páginas ('1 de 3') e as setas de navegação ('<' e '>'). Como a presença do rodapé nativo tem a maior prioridade, ele foi selecionado como o método de navegação principal. A lista de botões personalizados na lateral esquerda ('Summary', 'Media Analytics', etc.) foi ignorada, conforme as regras. O alvo foi definido como a seta de 'Próxima Página' ('>') dentro deste rodapé.",
    "nav_type": "native_footer",
    "page_count_visual": "1 de 3",
    "targets": [
        {
            "label": "Next Page Button",
            "x": 0.526,
            "y": 0.984
        }
    ]
}
```

---

## 💡 Potencial de Uso (Casos de Uso)

Os dados estruturados gerados por este interpretador habilitam aplicações poderosas:

### 1. Catálogo de Dados Inteligente
Alimente ferramentas de governança (como DataHub, Amundsen ou Notion) com metadados ricos e **prints atualizados** automaticamente, eliminando a documentação manual desatualizada.

### 2. Chatbot de Data Discovery (RAG)
Crie um assistente que ajuda usuários a encontrar o painel certo via chat natural:
*   **Input:** *"Onde vejo a performance de vendas por região?"*
*   **Matching:** Um modelo LLM compara a pergunta do usuário com o campo `perguntas_respondidas` do JSON gerado.
*   **Resposta:** *"Recomendo o painel **Sales Overview**. Ele responde 'Qual a performance regional?'. Veja uma prévia:"*
*   **Visual:** Exibe a imagem `00_home.png` para o usuário confirmar antes de clicar no link.

---

## ⚙️ Configuração Avançada (`config.py`)

Você pode ajustar a sensibilidade do robô:

* **`CLICK_ATTEMPT_OFFSETS`**: Lista de offsets gerada dinamicamente em círculos concêntricos.
* Por padrão: centro + 4 anéis × 8 direções = **33 pontos de tentativa**.
* Configurável via `_generate_concentric_offsets(max_radius, step)` em `config.py`.

* **`MAX_CONCURRENT_TASKS`**: Define quantos painéis serão processados simultaneamente no `batch_main.py` (padrão: 2). Ajuste conforme a RAM disponível.
* **`ROI_CROP`**: Define áreas da tela para ignorar no cálculo de duplicidade (ex: ignorar rodapé que contém relógio ou número de página, focando só nos gráficos).

## 🛠️ Solução de Problemas

**O robô clica, mas a página não muda?**
O sistema usa círculos concêntricos para encontrar o alvo. Se ainda falhar, verifique os logs para ver se a estabilização visual está detectando mudanças. Adicione mais offsets no `CLICK_ATTEMPT_OFFSETS` em `config.py` se necessário.

**Visuais carregando pela metade (mapas, gráficos)?**
A estabilização visual deveria resolver isso automaticamente. Se persistir, aumente o `max_wait_seconds` em `_wait_for_visual_stability()` no `bot_core.py`.

**Scroll capturando widget interno (tabela) em vez da página?**
O sistema seleciona o elemento de maior área com scroll que ocupe ≥60% do viewport. Se ainda selecionar errado, ajuste `min_area_ratio` em `_find_scroll_container()` no `bot_core.py`.

**Erros de "White Screen"?**
O sistema possui detecção automática de tela branca (erros de renderização do Power BI). Se a imagem for >99% branca, ela é ignorada e logada como erro, sem quebrar o fluxo. Isso evita falsos positivos em dashboards minimalistas legítimos.

## 📝 Licença

Este projeto é licenciado sob a **Apache License 2.0**.  
Consulte o arquivo [LICENSE](LICENSE) para mais detalhes.

A licença garante:
* ✅ Uso comercial livre.
* ✅ Modificação e distribuição permitidas.
* 🛡️ **Proteção contra processos de patentes**.
