import subprocess
import sys

def install():
    # Lista exata das dependências necessárias para o projeto
    packages = [
        "playwright",     # Automação do navegador
        "pillow",         # Processamento de imagem
        "imagehash",      # Comparação de imagens
        "google-genai",   # Inteligência Artificial
        "python-dotenv",  # Variáveis de ambiente
        "ipywidgets"      # Interface Visual para Notebooks
    ]
    
    print("🔧 Iniciando instalação de dependências...")
    for package in packages:
        print(f"   Instalando {package}...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        except subprocess.CalledProcessError:
            print(f"   ❌ Erro ao instalar {package}. Verifique sua conexão.")
            return

    print("\n🌍 Instalando navegadores do Playwright (Chromium)...")
    try:
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
    except subprocess.CalledProcessError:
        print("   ❌ Erro ao instalar navegador Chromium.")
        return
    
    print("\n✅ Tudo pronto! O ambiente está configurado.")
    print("Agora você pode rodar: !python main.py")
    
    # Cria flag de instalação
    with open(".deps_installed.txt", "w") as f:
        f.write("Instalacao concluida com sucesso.")

if __name__ == "__main__":
    install()