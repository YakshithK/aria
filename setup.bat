@echo off
setlocal EnableExtensions

set "ARIA_DIR=%~dp0"
set "MODEL=qwen3-next:80b-cloud"

echo Aria setup
echo ==========
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 or newer is required.
  echo Install it from https://www.python.org/downloads/windows/
  pause
  exit /b 1
)

python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 or newer is required.
  echo Install it from https://www.python.org/downloads/windows/
  pause
  exit /b 1
)

where uv >nul 2>nul
if errorlevel 1 (
  echo uv not found. Installing uv...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
  if errorlevel 1 (
    echo Failed to install uv.
    pause
    exit /b 1
  )
  set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"
)

where uv >nul 2>nul
if errorlevel 1 (
  echo uv is still not available on PATH. Open a new PowerShell window and re-run setup.bat.
  pause
  exit /b 1
)

echo Creating virtual environment...
uv venv "%ARIA_DIR%.venv"
if errorlevel 1 (
  echo Failed to create .venv.
  pause
  exit /b 1
)

echo Installing Aria...
uv pip install --python "%ARIA_DIR%.venv\Scripts\python.exe" -e "%ARIA_DIR%."
if errorlevel 1 (
  echo Failed to install Aria.
  pause
  exit /b 1
)

where ollama >nul 2>nul
if errorlevel 1 (
  start https://ollama.com/download
  echo Ollama is required. Install it, then re-run this script.
  pause
  exit /b 1
)

ollama list | findstr /I /C:"%MODEL%" >nul 2>nul
if errorlevel 1 (
  echo Pulling Ollama model %MODEL%...
  ollama pull "%MODEL%"
  if errorlevel 1 (
    echo Failed to pull Ollama model %MODEL%.
    pause
    exit /b 1
  )
)

echo Creating desktop shortcut...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\Aria.lnk'); $s.TargetPath = '%ARIA_DIR%.venv\Scripts\python.exe'; $s.Arguments = '-m aria tray'; $s.WorkingDirectory = '%ARIA_DIR%'; $s.Save()"
if errorlevel 1 (
  echo Failed to create desktop shortcut.
  pause
  exit /b 1
)

echo.
echo Aria setup complete.
echo Launch Aria from the desktop shortcut, or run:
echo   "%ARIA_DIR%.venv\Scripts\python.exe" -m aria tray
echo.
pause
exit /b 0
