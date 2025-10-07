@echo off
setlocal

set "ROOT=%~dp0"
cd /d "%ROOT%"

REM --- Проверяем Python 3.11 ---
for /f "tokens=2 delims= " %%p in ('py -V 2^>NUL') do set PYVER=%%p
if not defined PYVER (
  echo [ERROR] Python launcher py не найден.
  exit /b 1
)
for /f "tokens=1,2 delims=." %%a in ("%PYVER%") do (
  set MAJOR=%%a
  set MINOR=%%b
)
if not "%MAJOR%"=="3" goto :bad_python
if %MINOR% LSS 11 goto :bad_python

REM --- Создаём / переиспользуем venv ---
if not exist .venv (
  py -3.11 -m venv .venv
  if errorlevel 1 goto :bad_python
)

set "PY_EXE=%ROOT%\.venv\Scripts\python.exe"
set "PIP_EXE=%ROOT%\.venv\Scripts\pip.exe"

"%PY_EXE%" -m pip install --upgrade pip >nul
"%PIP_EXE%" install --no-cache-dir -r "legal_rag_gui\requirements.txt"
if errorlevel 1 goto :fail

set "PORT=8765"
set "BACKEND_LOG=%ROOT%\backend.log"
if exist "%BACKEND_LOG%" del "%BACKEND_LOG%"

REM --- Запускаем backend ---
start "Legal RAG Backend" /MIN "%PY_EXE%" -m uvicorn legal_rag_gui.backend.server:app --host 127.0.0.1 --port %PORT% --log-config None --use-colors

REM --- Ждём здоровье ---
powershell -NoProfile -Command "\
  $u='http://127.0.0.1:%PORT%/health'; \
  for($i=0;$i -lt 60;$i++){ \
    try{ $r=Invoke-RestMethod $u -TimeoutSec 1; if($r.ok){ exit 0 }} \
    catch{}; Start-Sleep -Milliseconds 500 \
  }; exit 1"
if errorlevel 1 (
  echo [ERROR] Backend не ответил. Смотрите backend.log
  powershell -NoProfile -Command "Get-Content -Path '%BACKEND_LOG%' -Tail 40"
  goto :kill_backend
)

echo Backend готов. Запускаем GUI...
"%PY_EXE%" -m legal_rag_gui.main
set "GUI_RC=%ERRORLEVEL%"

:kill_backend
taskkill /FI "WINDOWTITLE eq Legal RAG Backend" /T /F >nul 2>&1
endlocal & exit /b %GUI_RC%

:bad_python
echo [ERROR] Требуется установленный Python 3.11.
endlocal & exit /b 1

:fail
echo [ERROR] Не удалось установить зависимости.
endlocal & exit /b 1
