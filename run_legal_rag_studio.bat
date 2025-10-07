@echo off
setlocal

set "ROOT=%~dp0"
cd /d "%ROOT%"

REM === 0) ищем подходящий интерпретатор Python (>=3.11) ===
set "PY_CMD="
set "PY_FOUND_PATH="
for %%C in ("py -3.11" "py -3.12" "py -3.10" "py -3" "python") do (
  if not defined PY_CMD (
    call :CHECK_PY %%~C
  )
)

if not defined PY_CMD (
  echo [ERROR] Не найден установленный Python 3.11+. Установите x64-версию с https://www.python.org/ и повторите запуск.
  echo (подсказка: во время установки включите флажок "Add Python to PATH")
  pause
  exit /b 1
)

if defined PY_FOUND_PATH (
  echo [INFO] Используется интерпретатор: %PY_FOUND_PATH% (%PY_CMD%)
) else (
  echo [INFO] Используется интерпретатор: %PY_CMD%
)

REM === 1) создаём (или переиспользуем) виртуальное окружение ===
if exist "%ROOT%\.venv\Scripts\python.exe" (
  echo [INFO] Найдено существующее окружение .venv — переиспользуем.
) else (
  echo [INFO] Создаём виртуальное окружение .venv…
  call %PY_CMD% -m venv .venv || goto :py_fail
)

set "PY_EXE=%ROOT%\.venv\Scripts\python.exe"
set "PIP_EXE=%ROOT%\.venv\Scripts\pip.exe"

if not exist "%PY_EXE%" (
  echo [ERROR] Не удалось создать виртуальное окружение (.venv). Проверьте права доступа.
  goto :py_fail
)

REM === 2) зависимости (без кеша надёжнее) ===
echo [INFO] Обновляем pip и ставим зависимости…
"%PY_EXE%" -m pip install --upgrade pip >nul || goto :fail
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
echo [INFO] Запускаем backend (uvicorn)…
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

echo [INFO] Backend готов. Запускаем графический интерфейс…
"%PY_EXE%" -m legal_rag_gui.main
set "GUI_EXIT=%ERRORLEVEL%"

:kill_backend
taskkill /FI "WINDOWTITLE eq %BACKEND_TITLE%" /T /F >nul 2>&1

endlocal & exit /b %GUI_EXIT%

:fail
echo [ERROR] Установка зависимостей не удалась.
if exist "%BACKEND_LOG%" (
  echo --- backend.log ---
  powershell -NoProfile -Command "Get-Content -Path '%BACKEND_LOG%' -Tail 50"
)
pause
endlocal & exit /b 1

:py_fail
echo [ERROR] Не удалось запустить Python. Проверьте установлен ли Python 3.11+.
pause
endlocal & exit /b 1

REM === вспомогательная функция: проверяем кандидат на Python ===
:CHECK_PY
%* -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 || goto :EOF
for /f "usebackq delims=" %%E in (`%* -c "import sys; print(sys.executable)"`) do (
  set "PY_CMD=%*"
  set "PY_FOUND_PATH=%%~E"
)
goto :EOF
