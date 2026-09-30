# Natural-to-SQL - 1-Command Windows PowerShell Launcher
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Starting Natural-to-SQL Assistant...  " -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Check if uv is installed
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "[!] 'uv' not found. Installing uv..." -ForegroundColor Yellow
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
}

# Check if pnpm is installed and functional
$pnpmOk = $false
try {
    if (Get-Command pnpm -ErrorAction SilentlyContinue) {
        $testOut = & pnpm --version 2>&1
        if ($LASTEXITCODE -eq 0 -and $testOut -match '^\d+\.') { $pnpmOk = $true }
    }
} catch {
    $pnpmOk = $false
}

if (-not $pnpmOk) {
    Write-Host "[!] 'pnpm' not working or not found. Installing pnpm via npm..." -ForegroundColor Yellow
    npm install -g pnpm
}

# Launch Backend in a background process window
Write-Host "[1/2] Launching FastAPI Backend on http://127.0.0.1:8000..." -ForegroundColor Green
$backend = Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd backend; uv sync; uv run uvicorn app.main:app --reload --port 8000" -PassThru

# Launch Frontend in a background process window
Write-Host "[2/2] Launching Next.js Frontend on http://localhost:3000..." -ForegroundColor Green
$frontend = Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd frontend; pnpm install; pnpm dev" -PassThru

Write-Host ""
Write-Host "SUCCESS: Both services are running!" -ForegroundColor Green
Write-Host "👉 Open your browser to: http://localhost:3000" -ForegroundColor Yellow
Write-Host "👉 Backend docs:        http://127.0.0.1:8000/docs" -ForegroundColor Yellow
Write-Host ""
Write-Host "To stop the servers, close the opened PowerShell windows." -ForegroundColor Gray
