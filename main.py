import asyncio
import sys
import json
import os
from cataloger import DashboardCataloger

# Nome do arquivo temporário de troca de dados
CONFIG_FILE = "urls.json"

def load_urls():
    """Carrega URLs do arquivo JSON"""
    urls = []

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                urls = json.load(f)
                if isinstance(urls, list):
                    return urls
        except Exception as e:
            print(f"⚠️ Erro ao ler {CONFIG_FILE}: {e}")

    # Fallback: Lista vazia (retornará erro amigável)
    return []

async def main():
    urls_para_processar = load_urls()

    if not urls_para_processar:
        print("❌ Nenhuma URL encontrada!")
        print(f"   Certifique-se de que o notebook criou o arquivo '{CONFIG_FILE}'")
        return

    print(f"🚀 Iniciando processamento de {len(urls_para_processar)} dashboard(s)...\n")
    
    for i, url in enumerate(urls_para_processar):
        print(f"🔹 [{i+1}/{len(urls_para_processar)}] Processando: {url}")
        
        cataloger = DashboardCataloger()
        try:
            result = await cataloger.process_dashboard(url)
            
            if result:
                # Tenta pegar título de qualquer página que tenha análise
                paginas = result.get('pages', [])
                titulo = "Sem título"
                if paginas and 'analysis' in paginas[0]:
                    titulo = paginas[0]['analysis'].get('titulo', 'Sem título')
                
                print(f"   ✅ Sucesso! {len(paginas)} páginas encontradas.")
                print(f"   📄 Título: {titulo}")
            else:
                print("   ❌ Falha: Não foi possível catalogar.")
                
        except Exception as e:
            print(f"   ❌ Erro crítico: {e}")
            
        print("-" * 50)

    # Limpeza opcional: remove o arquivo temporário após uso
    # if os.path.exists(CONFIG_FILE): os.remove(CONFIG_FILE)
    
    print("\n🏁 Processamento finalizado!")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProcesso interrompido pelo usuário.")