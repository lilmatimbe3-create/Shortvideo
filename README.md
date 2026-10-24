# 🎬 ShortVideo AI Studio

Aplicação web com Inteligência Artificial que transforma vídeos longos (podcasts, aulas gravadas, emissões em direto) em **clips curtos prontos a publicar** (TikTok, Instagram Reels, YouTube Shorts), sem necessidade de ver o vídeo inteiro nem cortar manualmente.

---

## ⚙️ Como Funciona o Pipeline

1. **Entrega do Vídeo e Extração de Áudio (`app/transcriber.py`)**
   - O utilizador carrega o vídeo diretamente no browser.
   - O **FFmpeg** extrai a faixa de áudio em WAV mono a 16 kHz.
2. **Transcrição com Timestamps — O Mapa do Vídeo (`app/transcriber.py`)**
   - O modelo **faster-whisper** transcreve tudo o que é dito e regista o instante exato (`início` e `fim` em segundos e `MM:SS.ss`) de cada frase.
3. **Seleção dos Momentos Mais Fortes por IA (`app/analyzer.py`)**
   - Um modelo de linguagem (**Google Gemini**, **OpenAI GPT**, **Ollama local** ou o **motor heurístico local integrado**) lê o mapa do vídeo e identifica os excertos que fazem sentido sozinhos e têm maior potencial de retenção (uma ideia marcante, uma história bem contada ou uma resposta inesperada).
   - Para cada excerto, devolve título, categoria, pontuação de retenção (*hook score*), justificação e os segundos exatos de início e fim do corte.
4. **Recorte Automático e Pasta de Clips (`app/video_processor.py`)**
   - O programa recorta o vídeo original com **FFmpeg**, gerando ficheiros `.mp4` independentes e ficheiros de legendas `.srt` sincronizados.
   - Inclui opções avançadas para **Formato Vertical (9:16 - 1080×1920)** e **Legendas Automáticas Embutidas** no vídeo.
   - No fim, o utilizador pode pré-visualizar cada clip no browser, descarregar individualmente ou descarregar a pasta completa num ficheiro `.zip`.

---

## 🚀 Como Instalar e Executar

### 1. Pré-requisitos
- **Python 3.10+** instalado (se estiver no Windows e ainda não tiver o Python instalado, pode instalar com `winget install Python.Python.3.12`)
- **FFmpeg** (já detetado no sistema ou assegurado automaticamente via `imageio-ffmpeg`)

### 2. Criar ambiente virtual e instalar dependências
No terminal (PowerShell), dentro da pasta do projeto:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. Configurar Chave de API (Opcional)
Copie o ficheiro `.env.example` para `.env` (ou introduza a chave diretamente na interface web):

```powershell
Copy-Item .env.example .env
```
Pode usar:
- **Google Gemini** (`GEMINI_API_KEY`)
- **OpenAI** (`OPENAI_API_KEY`)
- **Ollama Local** (100% gratuito na sua máquina)
- **Modo Heurístico Local** (funciona mesmo sem chave de API)

### 4. Iniciar a Interface no Browser
```powershell
python run.py
```
Depois, abra no browser: **[http://127.0.0.1:8000](http://127.0.0.1:8000)**
