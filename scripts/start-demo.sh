#!/usr/bin/env bash
# Jalankan seluruh stack SiKembang (FastAPI + XGBoost + SQLite + React) dalam satu perintah.
# Penggunaan: bash scripts/start-demo.sh [--reset-db]
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

RESET_DB=false
if [[ "${1:-}" == "--reset-db" ]]; then
  RESET_DB=true
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN="python"
fi
command -v "$PYTHON_BIN" >/dev/null 2>&1 || { echo "Python 3.13+ tidak ditemukan."; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "Node.js / npm tidak ditemukan."; exit 1; }

VENV_PY="$ROOT_DIR/ml/.venv/bin/python"
if [[ ! -x "$VENV_PY" ]]; then
  echo "[1/5] Membuat Python virtualenv di ml/.venv ..."
  "$PYTHON_BIN" -m venv ml/.venv
fi

if ! "$VENV_PY" -c "import fastapi, uvicorn, xgboost, sqlalchemy, jwt, sikembang_backend" >/dev/null 2>&1; then
  echo "[2/5] Memasang dependensi backend Python (FastAPI, XGBoost, SQLAlchemy) ..."
  "$VENV_PY" -m pip install --upgrade pip
  "$VENV_PY" -m pip install -e "ml[backend]"
else
  echo "[2/5] Dependensi backend Python sudah siap."
fi

if [[ ! -d "$ROOT_DIR/node_modules" ]]; then
  echo "[3/5] Memasang dependensi frontend (npm install) ..."
  npm install
else
  echo "[3/5] Dependensi frontend (node_modules) sudah siap."
fi

mkdir -p ml/runtime
DB_PATH="ml/runtime/demo-dosen.sqlite3"
if [[ "$RESET_DB" == "true" && -f "$DB_PATH" ]]; then
  rm -f "$DB_PATH"
  echo "Database demo lama dihapus (--reset-db)."
fi

export SIKEMBANG_DB_PATH="$DB_PATH"
export SIKEMBANG_ARTIFACT="ml/artifacts/default"
export SIKEMBANG_JWT_SECRET="demo-local-jwt-secret-key-sikembang-32bytes-ok"
export SIKEMBANG_CORS_ORIGINS="http://localhost:5173,http://127.0.0.1:5173"
export SIKEMBANG_MARKETING_PASSWORD="demo-marketing-123"
export SIKEMBANG_PPIC_PASSWORD="demo-ppic-123456"
export SIKEMBANG_PFA_PASSWORD="demo-pfa-1234567"
export SIKEMBANG_DEVICE_RICE_KEY="demo-rice-sensor-key-000000000000001"
export SIKEMBANG_DEVICE_CHICKEN_KEY="demo-chicken-sensor-key-000000000002"
export SIKEMBANG_DEVICE_ESP32_KEY="demo-esp32-physical-rice-key-0000001"
unset SIKEMBANG_DEMO_CUTOFF || true

echo "[4/5] Menyiapkan SQLite, seed data minggu ini, dan registrasi sensor ..."
"$VENV_PY" -m sikembang_backend.manage init-db
"$VENV_PY" -m sikembang_backend.manage seed >/dev/null
"$VENV_PY" -m sikembang_backend.manage register-physical-rice --location GUDANG-UTAMA

echo "[5/5] Menyalakan FastAPI (port 8000) dan Frontend (port 5173) ..."
"$VENV_PY" -m uvicorn sikembang_backend.app:create_app --factory --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

cleanup() {
  echo ""
  echo "Menghentikan server backend FastAPI..."
  kill "$BACKEND_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

sleep 2
cat <<'EOF'

============================================================
  SiKembang Live Demo Siap Digunakan!
============================================================
  Frontend UI : http://localhost:5173
  Swagger API : http://127.0.0.1:8000/docs
  Health API  : http://127.0.0.1:8000/api/health

  Akun Demo (Username / Password):
    Marketing : marketing / demo-marketing-123
    PPIC      : ppic      / demo-ppic-123456
    PFA       : pfa       / demo-pfa-1234567

  X-Device-Key ESP32 (SNS-GDG-ESP32-01 -> ING-001 Beras):
    demo-esp32-physical-rice-key-0000001

  Tekan Ctrl+C untuk menghentikan backend & frontend.
============================================================

EOF

export VITE_API_MODE="live"
export VITE_API_BASE_URL="/api"
export VITE_DEV_PROXY_TARGET="http://127.0.0.1:8000"
npm run dev -- --host 127.0.0.1 --port 5173
