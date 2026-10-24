# Script de arranque automático para o ShortVideo AI Studio
$ErrorActionPreference = "Stop"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  ShortVideo AI Studio — Configuração e Arranque" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# Verificar se um Python real está instalado (ignorando o atalho da Microsoft Store)
$pythonCmd = $null
try {
    $ver = & python --version 2>&1
    if ($LASTEXITCODE -eq 0 -and $ver -match "Python 3") {
        $pythonCmd = "python"
    }
} catch {}

if (-not $pythonCmd) {
    Write-Host "[!] Python 3 não foi detetado no PATH. A instalar Python 3.12 via winget..." -ForegroundColor Yellow
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    $pythonCmd = "python"
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "[1/3] A criar ambiente virtual Python (.venv)..." -ForegroundColor Green
    & $pythonCmd -m venv .venv
}

Write-Host "[2/3] A instalar/verificar dependências (FastAPI, faster-whisper, Gemini/OpenAI, FFmpeg)..." -ForegroundColor Green
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
}

Write-Host "[3/3] A iniciar servidor em http://127.0.0.1:8000 ..." -ForegroundColor Green
Start-Process "http://127.0.0.1:8000"
& .\.venv\Scripts\python.exe run.py
