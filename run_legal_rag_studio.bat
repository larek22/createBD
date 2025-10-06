@echo off
setlocal

set "ROOT=%~dp0"
cd /d "%ROOT%"
set "GUI_EXIT=0"

set "PYTHON_CMD="
where python >nul 2>&1
if errorlevel 1 (
    where py >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Python 3.x is required but was not found in PATH.
        set "GUI_EXIT=1"
        goto :shutdown
    )
    set "PYTHON_CMD=py -3"
) else (
    set "PYTHON_CMD=python"
)

set "VENV_DIR=%ROOT%.venv"
if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo Creating virtual environment in %VENV_DIR%...
    %PYTHON_CMD% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [ERROR] Unable to create a virtual environment.
        set "GUI_EXIT=1"
        goto :shutdown
    )
)

call "%VENV_DIR%\Scripts\activate.bat"
if errorlevel 1 (
    echo [ERROR] Unable to activate the virtual environment.
    set "GUI_EXIT=1"
    goto :shutdown
)

echo Upgrading pip...
python -m pip install --upgrade pip
if errorlevel 1 (
    echo [ERROR] pip upgrade failed.
    set "GUI_EXIT=1"
    goto :shutdown
)

echo Installing Legal RAG Studio requirements...
if exist "%ROOT%legal_rag_gui\requirements.txt" (
    pip install -r "%ROOT%legal_rag_gui\requirements.txt"
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies.
        set "GUI_EXIT=1"
        goto :shutdown
    )
) else (
    echo [WARN] requirements file not found. Skipping dependency install.
)

set "BACKEND_PORT=8765"
for /f "usebackq delims=" %%P in (`python -c "from legal_rag_gui.utils.config import SettingsStore; print(SettingsStore().data.last_backend_port)" 2^>nul`) do set "BACKEND_PORT=%%P"

echo Using backend port %BACKEND_PORT%.
set "BACKEND_TITLE=LegalRAGBackend"

echo Starting backend server...
start "%BACKEND_TITLE%" cmd /c "call \"%VENV_DIR%\Scripts\activate.bat\" ^& python -m uvicorn legal_rag_gui.backend.server:app --host 127.0.0.1 --port %BACKEND_PORT%"

timeout /t 4 >nul

echo Launching Legal RAG Studio GUI...
python -m legal_rag_gui.main
set "GUI_EXIT=%ERRORLEVEL%"

:shutdown
echo.
echo Shutting down backend (if running)...
taskkill /FI "WINDOWTITLE eq %BACKEND_TITLE%" >nul 2>&1

if exist "%VENV_DIR%\Scripts\deactivate.bat" call "%VENV_DIR%\Scripts\deactivate.bat" >nul 2>&1

echo Done.
endlocal & exit /b %GUI_EXIT%
