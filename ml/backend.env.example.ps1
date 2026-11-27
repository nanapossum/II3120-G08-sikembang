# Copy to ml/runtime/backend.env.ps1 and provide separate local secrets before dot-sourcing.
$env:SIKEMBANG_DB_PATH = 'ml/runtime/sikembang.sqlite3'
$env:SIKEMBANG_ARTIFACT = 'ml/artifacts/xgb-v1-f9a770b940f71fc8'
$env:SIKEMBANG_JWT_SECRET = ''                  # At least 32 random bytes.
# $env:SIKEMBANG_SYSTEM_KEY = ''                # Optional. Generate a separate random key of at least 32 visible ASCII characters.
$env:SIKEMBANG_MARKETING_PASSWORD = ''
$env:SIKEMBANG_PPIC_PASSWORD = ''
$env:SIKEMBANG_PFA_PASSWORD = ''
$env:SIKEMBANG_DEVICE_RICE_KEY = ''             # Generate a distinct random 32+ character key.
$env:SIKEMBANG_DEVICE_CHICKEN_KEY = ''
# $env:SIKEMBANG_DEMO_CUTOFF = '2025-03-05T12:00:00+07:00'  # Historical synthetic replay only.
