@echo off
setlocal

set "ROOT=%~dp0"
cd /d "%ROOT%"

REM === 1) venv на Py 3.11 ===
py -3.11 -m venv .venv
if errorlevel 1 (
  echo [ERROR] Требуется Python 3.11 (x64). Установи с python.org.
  exit /b 1
)

set "PY_EXE=%ROOT%\.venv\Scripts\python.exe"
set "PIP_EXE=%ROOT%\.venv\Scripts\pip.exe"

"%PY_EXE%" -V >nul 2>&1 || (echo [ERROR] venv не создался & exit /b 1)

REM === 2) зависимости (без кеша надёжнее) ===
"%PY_EXE%" -m pip install --upgrade pip || goto :fail
"%PIP_EXE%" install --no-cache-dir -r "legal_rag_gui\requirements.txt" || goto :fail

REM === 3) ENV (локальный Qdrant не требует ключа) ===
set "QDRANT_URL=http://localhost:6333"
set "QDRANT_API_KEY="
REM set "OPENAI_API_KEY=..."   ^<-- ключ сюда руками/через системные переменные

set "PORT=8765"
set "BACKEND_TITLE=Legal RAG Backend"
set "BACKEND_LOG=%ROOT%\backend.log"

if exist "%BACKEND_LOG%" del "%BACKEND_LOG%"

REM === 4) старт backend (тем же интерпретатором venv), лог -> файл ===
start "%BACKEND_TITLE%" /MIN cmd /c ^
 ""%PY_EXE%" -m uvicorn legal_rag_gui.backend.server:app --host 127.0.0.1 --port %PORT% > "%BACKEND_LOG%" 2>&1"

REM === 5) ждём health (до ~30 сек) ===
powershell -NoProfile -Command ^
  "$u='http://127.0.0.1:%PORT%/health';" ^
  "for($i=0;$i -lt 60;$i++){" ^
  "  try{$r=Invoke-RestMethod $u -TimeoutSec 1; if($r.ok){exit 0}}catch{};" ^
  "  Start-Sleep -Milliseconds 500" ^
  "}; exit 1"

if errorlevel 1 (
  echo [ERROR] Backend не поднялся. Последние строки лога:
  powershell -NoProfile -Command "Get-Content -Path '%BACKEND_LOG%' -Tail 50"
  goto :kill_backend
)

REM === 6) запуск GUI тем же интерпретатором ===
"%PY_EXE%" -m legal_rag_gui.main
set "GUI_EXIT=%ERRORLEVEL%"

:kill_backend
taskkill /FI "WINDOWTITLE eq %BACKEND_TITLE%" /T /F >nul 2>&1

endlocal & exit /b %GUI_EXIT%

:fail
echo [ERROR] Установка зависимостей не удалась.
endlocal & exit /b 1
