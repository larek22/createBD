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
call .\.venv\Scripts\activate

REM === 2) зависимости
python -m pip install --upgrade pip
if errorlevel 1 goto :fail
pip install -r legal_rag_gui\requirements.txt
if errorlevel 1 goto :fail

REM === 3) порт backend
set "PORT=8765"

REM === 4) старт backend
set "BACKEND_TITLE=Legal RAG Backend"
start "%BACKEND_TITLE%" cmd /c "call .\\.venv\\Scripts\\activate ^& uvicorn legal_rag_gui.backend.server:app --host 127.0.0.1 --port %PORT%"

REM === 5) запуск GUI
python -m legal_rag_gui.main
set "GUI_EXIT=%ERRORLEVEL%"

taskkill /FI "WINDOWTITLE eq %BACKEND_TITLE%" >nul 2>&1
call .\.venv\Scripts\deactivate >nul 2>&1
endlocal & exit /b %GUI_EXIT%

:fail
echo [ERROR] Не удалось подготовить окружение.
endlocal & exit /b 1
