import io
import re
import logging
import imagehash
from typing import Optional, List, Union, Tuple
from PIL import Image
from datetime import datetime
from config import ROI_CROP


def setup_logger(name: str = "Cataloger") -> logging.Logger:
    """Configura um logger simples com output no console."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    if not logger.handlers:
        ch = logging.StreamHandler()
        formatter = logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s', datefmt='%H:%M:%S')
        ch.setFormatter(formatter)
        logger.addHandler(ch)
        
    return logger


def parse_page_count(text: str) -> Optional[int]:
    # type: (str) -> Optional[int]
    """
    Extrai o total de páginas de textos de navegação.
    
    Suporta formatos:
    - "1 de 4", "2 de 10" (português)
    - "1 of 4", "3 of 15" (inglês)  
    - "1/4", "2/7" (barra)
    - "1 - 4", "1 – 4" (hífen/travessão)
    
    Returns:
        Total de páginas (int) ou None se não encontrar padrão válido.
    """
    if not text:
        return None
        
    patterns = [
        r'(\d+)\s*(?:de|of)\s*(\d+)',   # "1 de 4", "1 of 4"
        r'(\d+)\s*/\s*(\d+)',            # "1/4", "1 / 4"
        r'(\d+)\s*[-–—]\s*(\d+)',        # "1 - 4", "1 – 4", "1 — 4"
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(2))  # Retorna o total (segundo número)
    
    return None

def bytes_to_image(img_bytes: bytes) -> Image.Image:
    """Converte bytes para objeto PIL Image."""
    return Image.open(io.BytesIO(img_bytes)).convert('RGB')

def crop_roi_image(pil_image: Image.Image, nav_type: str = "default") -> Image.Image:
    """Realiza o crop na imagem baseado no tipo de navegação."""
    crop_coords = ROI_CROP.get(nav_type, ROI_CROP["default"])
    w, h = pil_image.size
    
    left = int(w * crop_coords[0])
    top = int(h * crop_coords[1])
    right = int(w * crop_coords[2])
    bottom = int(h * crop_coords[3])
    
    return pil_image.crop((left, top, right, bottom))

def compute_phash(pil_image: Image.Image, nav_type: str = "default") -> imagehash.ImageHash:
    """Calcula o hash perceptual da imagem (focando na ROI)."""
    roi = crop_roi_image(pil_image, nav_type)
    return imagehash.phash(roi)

def sanitize_filename(title: str, max_length: int = 50) -> str:
    """
    Converte um título em nome de arquivo seguro.
    
    - Remove caracteres especiais (mantém letras, números, espaços, hífens)
    - Substitui espaços por underscore
    - Limita tamanho
    - Retorna string vazia se título for inválido
    """
    if not title or title == "Sem título":
        return ""
    
    # Remove caracteres não permitidos em nomes de arquivo
    safe = re.sub(r'[<>:"/\\|?*]', '', title)
    # Substitui espaços e múltiplos underscores
    safe = re.sub(r'\s+', '_', safe.strip())
    safe = re.sub(r'_+', '_', safe)
    # Remove underscores no início/fim
    safe = safe.strip('_')
    # Limita tamanho
    if len(safe) > max_length:
        safe = safe[:max_length].rstrip('_')
    
    return safe.lower()


def is_error_screen(pil_image: Image.Image) -> bool:
    """
    Heurística ajustada: tolerar mais branco.
    """
    img_small = pil_image.resize((100, 100))
    pixels = list(img_small.getdata())
    
    # 9900 (99%)
    # Aumentado para suportar dashboards "clean" (fundo branco)
    white = sum(1 for r,g,b in pixels if r > 240 and g > 240 and b > 240)
    
    # Se >99% branco = provável erro (tela branca da morte)
    return (white > 9900)

def clamp(value: float, min_val: float = 0, max_val: float = 1) -> float:
    """Restringe um valor entre min_val e max_val."""
    return max(min_val, min(max_val, value))