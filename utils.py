import io
import logging
import imagehash
from PIL import Image
from datetime import datetime
from config import ROI_CROP

def setup_logger(name="Cataloger"):
    """Configura um logger simples com output no console."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    if not logger.handlers:
        ch = logging.StreamHandler()
        formatter = logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s', datefmt='%H:%M:%S')
        ch.setFormatter(formatter)
        logger.addHandler(ch)
        
    return logger

def bytes_to_image(img_bytes):
    """Converte bytes para objeto PIL Image."""
    return Image.open(io.BytesIO(img_bytes)).convert('RGB')

def crop_roi_image(pil_image, nav_type="default"):
    """Realiza o crop na imagem baseado no tipo de navegação."""
    crop_coords = ROI_CROP.get(nav_type, ROI_CROP["default"])
    w, h = pil_image.size
    
    left = int(w * crop_coords[0])
    top = int(h * crop_coords[1])
    right = int(w * crop_coords[2])
    bottom = int(h * crop_coords[3])
    
    return pil_image.crop((left, top, right, bottom))

def compute_phash(pil_image, nav_type="default"):
    """Calcula o hash perceptual da imagem (focando na ROI)."""
    roi = crop_roi_image(pil_image, nav_type)
    return imagehash.phash(roi)

def is_error_screen(pil_image):
    """
    Heurística ajustada: tolerar mais branco.
    """
    img_small = pil_image.resize((100, 100))
    pixels = list(img_small.getdata())
    
    # 9500 (98%)
    # Dashboards clean costumam ser muito brancos.
    white = sum(1 for r,g,b in pixels if r > 240 and g > 240 and b > 240)
    
    # Se >98% branco = provável erro
    return (white > 9500)