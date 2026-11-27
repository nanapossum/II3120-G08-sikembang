<#
.SYNOPSIS
    Jalankan seluruh stack SiKembang (FastAPI + XGBoost + SQLite + React) dalam satu perintah.
.DESCRIPTION
    Menyiapkan venv Python & node_modules jika belum ada, menginisialisasi database demo
    (ml/runtime/demo-dosen.sqlite3) beserta seed & perangkat ESP32, lalu menyalakan
    backend (port 8000) dan frontend (port 5173). Tekan Ctrl+C untuk menghentikan keduanya.
.PARAMETER ResetDb
    Hapus database demo lama dan buat ulang dari awal (bersih tanpa draf sebelumnya).
#>
param(
    [switch]$ResetDb
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root

function Find-Python {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($ver in @('-3.13', '-3.14', '-3')) {
            try {
                & py $ver --version *> $null
                if ($LASTEXITCODE -eq 0) { return @('py', $ver) }
            } catch {}
        }
    }
    foreach ($cmd in @('python', 'python3')) {
        if (Get-Command $cmd -ErrorAction SilentlyContinue) {
            return @($cmd)
        }
    }
    throw 'Python 3.13+ tidak ditemukan. Pasang Python 3.13+ terlebih dahulu.'
}

if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw 'Node.js / npm tidak ditemukan. Pasang Node.js 20+ terlebih dahulu.'
}

# 1. Siapkan Python virtualenv + dependensi backend
$venvPython = Join-Path $root 'ml\.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    Write-Host '[1/5] Membuat Python virtualenv di ml/.venv ...' -ForegroundColor Cyan
    $pyCmd = Find-Python
    if ($pyCmd.Length -eq 2) {
        & $pyCmd[0] $pyCmd[1] -m venv ml/.venv
    } else {
        & $pyCmd[0] -m venv ml/.venv
    }
    if ($LASTEXITCODE -ne 0) { throw 'Gagal membuat virtualenv Python.' }
}

& $venvPython -c "import fastapi, uvicorn, xgboost, sqlalchemy, jwt, sikembang_backend" *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host '[2/5] Memasang dependensi backend Python (FastAPI, XGBoost, SQLAlchemy) ...' -ForegroundColor Cyan
    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install -e "ml[backend]"
    if ($LASTEXITCODE -ne 0) { throw 'Gagal memasang dependensi Python.' }
} else {
    Write-Host '[2/5] Dependensi backend Python sudah siap.' -ForegroundColor Green
}

# 2. Siapkan dependensi frontend
if (-not (Test-Path (Join-Path $root 'node_modules'))) {
    Write-Host '[3/5] Memasang dependensi frontend (npm install) ...' -ForegroundColor Cyan
    & npm.cmd install
    if ($LASTEXITCODE -ne 0) { throw 'Gagal menjalankan npm install.' }
} else {
    Write-Host '[3/5] Dependensi frontend (node_modules) sudah siap.' -ForegroundColor Green
}

# 3. Environment & database demo lokal
New-Item -ItemType Directory -Force (Join-Path $root 'ml\runtime') | Out-Null
$dbPath = 'ml/runtime/demo-dosen.sqlite3'
if ($ResetDb -and (Test-Path $dbPath)) {
    Remove-Item -Force $dbPath
    Write-Host 'Database demo lama dihapus (-ResetDb).' -ForegroundColor Yellow
}

$env:SIKEMBANG_DB_PATH = $dbPath
$env:SIKEMBANG_ARTIFACT = 'ml/artifacts/default'
$env:SIKEMBANG_JWT_SECRET = 'demo-local-jwt-secret-key-sikembang-32bytes-ok'
$env:SIKEMBANG_CORS_ORIGINS = 'http://localhost:5173,http://127.0.0.1:5173'
$env:SIKEMBANG_MARKETING_PASSWORD = 'demo-marketing-123'
$env:SIKEMBANG_PPIC_PASSWORD = 'demo-ppic-123456'
$env:SIKEMBANG_PFA_PASSWORD = 'demo-pfa-1234567'
$env:SIKEMBANG_DEVICE_RICE_KEY = 'demo-rice-sensor-key-000000000000001'
$env:SIKEMBANG_DEVICE_CHICKEN_KEY = 'demo-chicken-sensor-key-000000000002'
$env:SIKEMBANG_DEVICE_ESP32_KEY = 'demo-esp32-physical-rice-key-0000001'
Remove-Item Env:SIKEMBANG_DEMO_CUTOFF -ErrorAction SilentlyContinue

Write-Host '[4/5] Menyiapkan SQLite, seed data minggu ini, dan registrasi sensor ...' -ForegroundColor Cyan
& $venvPython -m sikembang_backend.manage init-db
if ($LASTEXITCODE -ne 0) { throw 'init-db gagal.' }
& $venvPython -m sikembang_backend.manage seed | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'seed gagal. Jalankan ulang dengan -ResetDb bila perlu.' }
& $venvPython -m sikembang_backend.manage register-physical-rice --location GUDANG-UTAMA
if ($LASTEXITCODE -ne 0) { throw 'register-physical-rice gagal.' }

# 4. Jalankan backend FastAPI (background) dan frontend Vite (foreground)
Write-Host '[5/5] Menyalakan FastAPI (port 8000) dan Frontend (port 5173) ...' -ForegroundColor Cyan
$backendProc = Start-Process -FilePath $venvPython `
    -ArgumentList '-m', 'uvicorn', 'sikembang_backend.app:create_app', '--factory', '--host', '0.0.0.0', '--port', '8000' `
    -WorkingDirectory $root `
    -NoNewWindow `
    -PassThru

try {
    Start-Sleep -Seconds 2
    Write-Host ''
    Write-Host '============================================================' -ForegroundColor Green
    Write-Host '  SiKembang Live Demo Siap Digunakan!' -ForegroundColor Green
    Write-Host '============================================================' -ForegroundColor Green
    Write-Host '  Frontend UI : http://localhost:5173'
    Write-Host '  Swagger API : http://127.0.0.1:8000/docs'
    Write-Host '  Health API  : http://127.0.0.1:8000/api/health'
    Write-Host ''
    Write-Host '  Akun Demo (Username / Password):'
    Write-Host '    Marketing : marketing / demo-marketing-123'
    Write-Host '    PPIC      : ppic      / demo-ppic-123456'
    Write-Host '    PFA       : pfa       / demo-pfa-1234567'
    Write-Host ''
    Write-Host '  X-Device-Key ESP32 (SNS-GDG-ESP32-01 -> ING-001 Beras):'
    Write-Host '    demo-esp32-physical-rice-key-0000001'
    Write-Host ''
    Write-Host '  Tekan Ctrl+C untuk menghentikan backend & frontend.' -ForegroundColor Yellow
    Write-Host '============================================================' -ForegroundColor Green
    Write-Host ''

    $env:VITE_API_MODE = 'live'
    $env:VITE_API_BASE_URL = '/api'
    $env:VITE_DEV_PROXY_TARGET = 'http://127.0.0.1:8000'
    & npm.cmd run dev -- --host 127.0.0.1 --port 5173
} finally {
    if ($backendProc -and -not $backendProc.HasExited) {
        Write-Host ''
        Write-Host 'Menghentikan server backend FastAPI...' -ForegroundColor Yellow
        Stop-Process -Id $backendProc.Id -Force -ErrorAction SilentlyContinue
    }
}
