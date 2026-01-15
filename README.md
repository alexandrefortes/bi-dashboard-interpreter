[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

# bi-dashboard-interpreter

*A focused crawler for BI dashboards (UI-level, non-invasive).*

Este projeto utiliza IA Multimodal (Gemini 2.5) e Automação de Navegador (Playwright) para navegar, capturar e documentar funcionalmente painéis de Business Intelligence (Power BI, etc.) automaticamente.

> **Nota de uso:** Execute apenas com credenciais próprias e em conteúdos cuja captura/armazenamento (prints e metadados) seja permitido pelas políticas do ambiente.

## 🧱 Modularização

O código segue princípios de responsabilidade única:
* **`main.py`**: Orquestrador de entrada.
* **`cataloger.py`**: Lógica de fluxo (Batedor -> Explorador -> Analista).
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

* **Saída:** Lista de coordenadas (x, y) de onde clicar.

### 2. The Explorer (O Explorador)

* **Função:** Navegar com resiliência.
* **Lógica de "Cross Search" (Busca em Cruz):**
* O robô tenta clicar na coordenada sugerida pelo Scout.
* Verifica se a tela mudou (usando Hash Visual).
* **Se falhar:** Ele tenta clicar automaticamente um pouco para cima, baixo, esquerda e direita (offsets configuráveis em `config.py`) para compensar imprecisões do modelo.
* **Fallback (Último recurso):** Se for navegação nativa e o clique visual falhar, ele injeta cliques via DOM (HTML) nos botões do Power BI.

### 3. The Analyst (O Analista)

* **Função:** Documentação de Negócio.
* **Lógica:** Analisa apenas as páginas únicas validadas.
* **Saída:** Gera descrições funcionais (título, objetivo, filtros, público-alvo) ignorando dados voláteis (números do dia), focando na estrutura analítica.

### Adendo sobre captura de tela:

1. Acesso inicial ou clique para mudar de página
2. Espera carregar (3-5 segundos)
3. Chama get_full_page_screenshot_bytes() que:
    ├─ Volta ao topo (scrollTop = 0)
    ├─ Detecta se tem scroll
    ├─ Se sim: captura múltiplas vezes enquanto rola
    ├─ Une as capturas
    └─ Volta ao topo novamente
4. Salva a imagem final

---

## 📂 Estrutura de Saída

Cada execução cria uma pasta única dentro de `runs/` com o timestamp da execução:

```text
runs/
└── 20260113_213721/            # ID da Execução (Data_Hora)
    ├── catalog.json            # O "Ouro": Metadados completos do dashboard
    └── screenshots/            # Evidências visuais
        ├── 00_home.png         # Tela inicial
        ├── 01_target.png       # Página 2 (após clique)
        ├── 02_target.png       # Página 3 (após clique)
        └── ...

```

### Exemplo de `catalog.json`

O arquivo JSON final consolida a navegação técnica e a análise de negócios. Exemplo:

```json
{
  "url": "[https://app.powerbi.com/](https://app.powerbi.com/)...",
  "pages": [
    {
      "id": 0,
      "label": "Home",
      "analysis": {
        "titulo_painel": "Titanic Dataset Analysis",
        "objetivo_macro": "Análise exploratória de fatores de sobrevivência...",
        "perguntas_respondidas": [
          "Qual a taxa de sobrevivência por gênero?",
          "A classe da passagem influencia na sobrevivência?"
        ],
        "publico_sugerido": "Cientista de Dados"
      }
    }
  ]
}

```

---

## ⚙️ Configuração Avançada (`config.py`)

Você pode ajustar a sensibilidade do robô:

* **`CLICK_ATTEMPT_OFFSETS`**: Lista de pixels para a "Busca em Cruz".
* Ex: `[(0,0), (0, 20), (0, -20)]` tenta no centro, depois 20px pra baixo, depois pra cima.


* **`PHASH_THRESHOLD`**: Sensibilidade para detectar mudança de página. (Padrão: 8).
* **`ROI_CROP`**: Define áreas da tela para ignorar no cálculo de duplicidade (ex: ignorar rodapé que contém relógio ou número de página, focando só nos gráficos).

## 🛠️ Solução de Problemas

**O robô clica, mas a página não muda?**
Verifique se o dashboard é muito pesado. Aumente o `asyncio.sleep` no `cataloger.py` ou adicione mais offsets no `CLICK_ATTEMPT_OFFSETS` em `config.py`.

**Erros de "White Screen"?**
O sistema possui detecção automática de tela branca (erros de renderização do Power BI). Se a imagem for >98% branca, ela é ignorada e logada como erro, sem quebrar o fluxo.

## 📝 Licença

Este projeto é licenciado sob a **Apache License 2.0**.  
Consulte o arquivo [LICENSE](LICENSE) para mais detalhes.

A licença garante:
* ✅ Uso comercial livre.
* ✅ Modificação e distribuição permitidas.
* 🛡️ **Proteção contra processos de patentes** (contribuição segura).
