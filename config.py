import os
from dotenv import load_dotenv

# Carrega variáveis de ambiente
load_dotenv()

# ============================================
# CONFIGURAÇÃO GERAL
# ============================================

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Modelos (Usando strings compatíveis com a nova SDK google-genai)
MODEL_SCOUT = "gemini-2.5-pro"
MODEL_ANALYST = "gemini-2.5-pro"

# Configurações de Comparação Visual
PHASH_THRESHOLD = 8  # Diferença mínima para considerar mudança de página
DUPLICATE_THRESHOLD = 4 # Diferença máxima para considerar página duplicada (já vista)

# Configurações de Diretório
OUTPUT_DIR = "runs"

# Configurações de Viewport (Seguindo seu playwright_bot.py)
VIEWPORT = {'width': 1920, 'height': 1080}

# Configurações de Navegação e Resiliência
# Offsets em pixels (x, y) para tentativa de clique em cruz (Cross Search)
# Ordem: Centro, Cima, Baixo, Esquerda, Direita
CLICK_ATTEMPT_OFFSETS = [(0, 0), (0, -20), (0, 20), (-20, 0), (20, 0)]

# ROIs para ignorar partes da imagem no cálculo do hash (nav_type -> crop box)
# Formato: (left_pct, top_pct, right_pct, bottom_pct)
ROI_CROP = {
    "bottom_tabs": (0, 0, 1, 0.90),    # remove 10% inferior
    "left_list": (0.20, 0, 1, 1),      # remove 20% esquerda
    "top_tabs": (0, 0.08, 1, 1),       # remove 8% superior
    "default": (0, 0, 1, 1)            # imagem inteira
}