import json
import logging
from google import genai
from google.genai import types
from config import GEMINI_API_KEY, MODEL_SCOUT, MODEL_ANALYST, VIEWPORT


logger = logging.getLogger("Cataloger")

class GeminiService:
    def __init__(self):
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY não encontrada nas variáveis de ambiente.")
        
        self.client = genai.Client(api_key=GEMINI_API_KEY)

    def _call_gemini(self, model_name, prompt_text, image_bytes, response_schema=None):
        """Método genérico para chamar a API nova do Google GenAI."""
        try:
            image_part = types.Part.from_bytes(
                data=image_bytes,
                mime_type="image/png"
            )
            
            text_part = types.Part.from_text(text=prompt_text)
            
            contents = [
                types.Content(
                    role="user",
                    parts=[text_part, image_part]
                )
            ]

            # Configuração de geração
            generate_config = types.GenerateContentConfig(
                response_mime_type="application/json" if response_schema else "text/plain",
                response_schema=response_schema
            )

            response = self.client.models.generate_content(
                model=model_name,
                contents=contents,
                config=generate_config
            )

            return response.text

        except Exception as e:
            logger.error(f"Erro na chamada LLM ({model_name}): {e}")
            return None

    def discover_navigation(self, image_bytes):
        """Estágio B: Identifica elementos de navegação com prioridade para paginação nativa."""
        prompt = """
        Analise esta captura de tela de um relatório Power BI.
        Sua missão é identificar O PRINCIPAL método de navegação para acessar as diferentes páginas do relatório.

        Prioridade de Identificação (em ordem):
        1. **Rodapé Nativo (Native Footer)**: Procure na parte INFERIOR por uma barra cinza estreita contendo texto como "1 of X", "1 de 4" ou setas de navegação (< >). 
           - Se existir, esse é o "nav_type": "native_footer".
           - O "target" deve ser APENAS a seta de "Próxima Página" (>).

        2. **Abas de Conteúdo (Custom Tabs)**: Se NÃO houver rodapé nativo, procure por botões ou abas desenhados dentro do relatório (topo ou lateral) que pareçam trocar a visão inteira.
           - Tipos: "top_tabs", "left_list", "bottom_tabs".
           - Os "targets" são as coordenadas centrais de cada aba visível.

        Ignore filtros, slicers de data ou botões de "Voltar".

        IMPORTANTE: Coordenadas devem ser NORMALIZADAS entre 0.0 e 1.0 (proporção da tela).
        Exemplo: centro da tela = 0.5, 0.5 | canto superior esquerdo = 0.0, 0.0 | canto inferior direito = 1.0, 1.0

        Retorne estritamente JSON:
        {
            "nav_reflection": "Sua justificativa e análise aqui. Por quê fez essas escolhas? Se encontrou outros métodos de navegação além do native_footer comente sobre eles.",
            "nav_type": "native_footer" | "top_tabs" | "left_list" | "none",
            "page_count_visual": "Texto exato visto indicando contagem (ex: '1 of 4') ou null",
            "targets": [
                {"label": "Next Page Button" ou "Nome da Aba", "x": 0.0, "y": 0.0}
            ]
        }
        """
        
        scout_schema = {
            "type": "OBJECT",
            "properties": {
                "nav_reflection": {"type": "STRING"},
                "nav_type": {
                    "type": "STRING",
                    "enum": ["native_footer", "top_tabs", "left_list", "bottom_tabs", "none"]
                },
                "page_count_visual": {"type": "STRING", "nullable": True},
                "targets": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "label": {"type": "STRING"},
                            "x": {"type": "NUMBER"},
                            "y": {"type": "NUMBER"}
                        },
                        "required": ["label", "x", "y"]
                    }
                }
            },
            "required": ["nav_reflection", "nav_type", "targets"]
        }

        json_text = self._call_gemini(
            MODEL_SCOUT, 
            prompt, 
            image_bytes, 
            response_schema=scout_schema
        )
        
        base_result = {"nav_type": "none", "targets": [], "raw_response": json_text}

        if not json_text:
            return base_result

        try:
            # Com esquema rígido, não precisamos de regex para limpar markdown
            data = json.loads(json_text)
            
            # Garante que raw_response esteja presente no dicionário final
            if isinstance(data, dict):
                data["raw_response"] = json_text
            else:
                data = base_result
            
            # Se o modelo devolveu pixels (ex: > 1), normaliza usando VIEWPORT
            targets = data.get("targets", [])
            needs_conversion = any(t.get('x', 0) > 1 or t.get('y', 0) > 1 for t in targets)
            
            if needs_conversion:
                logger.warning("⚠️ Scout retornou coordenadas em pixels, convertendo para normalizadas...")
                for target in targets:
                    if target.get('x', 0) > 1: 
                        target['x'] = target['x'] / VIEWPORT['width']
                    if target.get('y', 0) > 1: 
                        target['y'] = target['y'] / VIEWPORT['height']
                
            return data

        except json.JSONDecodeError:
            logger.error(f"Falha ao decodificar JSON do Scout. Recebido: {json_text}")
            return base_result

    def analyze_page(self, image_bytes):
        """Estágio D: Documentação Funcional (Abstrata e Atemporal)."""
        prompt = """
        Atue como um Arquiteto de BI responsável por catalogar ativos de dados da empresa.
        Sua tarefa é descrever a FUNCIONALIDADE e o PROPÓSITO deste dashboard para um catálogo de governança.
        
        REGRAS CRÍTICAS:
        1. NÃO extraia números específicos, datas exatas ou valores visíveis (ex: não diga "O score é 50", diga "Exibe o score atual").
        2. NÃO tire insights do momento (ex: não diga "A venda caiu", diga "Permite analisar tendência de vendas").
        3. A descrição deve ser válida hoje, mês que vem ou ano que vem, independente dos dados mudarem.
        
        Analise a imagem e gere um JSON estrito com:
        
        {
          "titulo_painel": "Título oficial identificado no topo",
          "objetivo_macro": "Para que serve este painel? (Ex: 'Monitoramento de performance operacional' ou 'Comparativo estratégico entre países')",
          "perguntas_respondidas": [
             "Liste 3 a 5 perguntas de negócio que um usuário consegue responder usando esta tela.",
             "Ex: 'Quais países lideram o ranking no ano selecionado?'",
             "Ex: 'Existe correlação entre PIB e a métrica de inovação?'",
             "Ex: 'Qual a evolução histórica do indicador selecionado?'"
          ],
          "dominio_negocio": "Área funcional (ex: Financeiro, Vendas, RH, Logística, Marketing)",
          "elementos_visuais": "Descreva a estrutura abstrata (Ex: 'Matriz de gráficos de barras comparativos por ano' ou 'Gráfico de dispersão (Scatter Plot) correlacionando duas variáveis com tamanho da bolha indicando população')",
          "filtros_visiveis": ["Lista de filtros/slicers disponíveis"],
          "principais_indicadores": ["Lista de métricas/KPIs visíveis (ex: Receita Total, Qtd Vendas)"],
          "publico_sugerido": "Executivo, Analista de Mercado, Operacional ou Cientista de Dados"
        }
        
        Use linguagem técnica de negócios em Português.
        """
        
        analyst_schema = {
            "type": "OBJECT",
            "properties": {
                "titulo_painel": {"type": "STRING"},
                "objetivo_macro": {"type": "STRING"},
                "perguntas_respondidas": {"type": "ARRAY", "items": {"type": "STRING"}},
                "dominio_negocio": {"type": "STRING"},
                "elementos_visuais": {"type": "STRING"},
                "filtros_visiveis": {"type": "ARRAY", "items": {"type": "STRING"}},
                "principais_indicadores": {"type": "ARRAY", "items": {"type": "STRING"}},
                "publico_sugerido": {"type": "STRING"}
            },
            "required": [
                "titulo_painel", "objetivo_macro", "perguntas_respondidas",
                "dominio_negocio", "elementos_visuais", "filtros_visiveis",
                "principais_indicadores", "publico_sugerido"
            ]
        }

        json_text = self._call_gemini(
            MODEL_ANALYST, 
            prompt, 
            image_bytes, 
            response_schema=analyst_schema
        )

        if not json_text:
            return {"erro": "Falha na análise LLM"}

        try:
            return json.loads(json_text)
        except json.JSONDecodeError:
            logger.error(f"JSON Inválido no Analyst: {json_text}")
            return {"erro": "JSON inválido retornado pelo LLM"}