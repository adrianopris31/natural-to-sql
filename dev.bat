@echo off
title Natural-to-SQL Launcher
echo ========================================
echo   Starting Natural-to-SQL Assistant...  
echo ========================================

echo [1/2] Launching Backend on http://127.0.0.1:8000...
start "Natural-to-SQL Backend" cmd /k "cd backend && uv sync && uv run uvicorn app.main:app --reload --port 8000"

echo [2/2] Launching Frontend on http://localhost:3000...
start "Natural-to-SQL Frontend" cmd /k "cd frontend && pnpm install && pnpm dev"

echo.
echo Application launched!
echo Open your browser to: http://localhost:3000
echo.
pause
