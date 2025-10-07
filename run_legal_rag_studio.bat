@echo off
setlocal

set "ROOT=%~dp0"
cd /d "%ROOT%"

REM === 1) venv на Py 3.11
py -3.11 -m venv .venv
if errorlevel 1 (
    echo [ERROR] Требуется Python 3.11 (установи с python.org).
    exit /b 1
)
set "PYTHON=.\.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo [ERROR] Виртуальное окружение не создано корректно.
    exit /b 1
)

call .\.venv\Scripts\activate

REM === 2) зависимости
"%PYTHON%" -m pip install --upgrade pip
if errorlevel 1 goto :fail
"%PYTHON%" -m pip install -r legal_rag_gui\requirements.txt
if errorlevel 1 goto :fail

REM === 3) порт backend
set "PORT=8765"
set "BACKEND_TITLE=Legal RAG Backend"

REM === 4) старт backend тем же интерпретатором
start "%BACKEND_TITLE%" /MIN "%PYTHON%" -m uvicorn ^
  legal_rag_gui.backend.server:app --host 127.0.0.1 --port %PORT%

REM === 5) ожидание готовности backend
powershell -NoProfile -Command ^
  "$u='http://127.0.0.1:%PORT%/health';" ^
  "for($i=0;$i -lt 60;$i++){try{$r=Invoke-RestMethod $u -TimeoutSec 1;if($r.ok){exit 0}}catch{};Start-Sleep -Milliseconds 500};exit 1"
if errorlevel 1 goto :backend_fail

REM === 6) запуск GUI тем же интерпретатором
"%PYTHON%" -m legal_rag_gui.main
set "GUI_EXIT=%ERRORLEVEL%"

:shutdown
taskkill /FI "WINDOWTITLE eq %BACKEND_TITLE%" >nul 2>&1
call .\.venv\Scripts\deactivate >nul 2>&1
endlocal & exit /b %GUI_EXIT%

:backend_fail
echo [ERROR] Backend не ответил по адресу http://127.0.0.1:%PORT%/health.
set "GUI_EXIT=1"
goto :shutdown

:fail
echo [ERROR] Не удалось подготовить окружение.
set "GUI_EXIT=1"
goto :shutdown
