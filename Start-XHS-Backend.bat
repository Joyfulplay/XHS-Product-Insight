@echo off
setlocal

title XHS Product Insight Backend

echo Starting XHS Product Insight backend...
echo.

where wsl.exe >nul 2>nul
if errorlevel 1 (
  echo ERROR: WSL is not installed or wsl.exe is not available.
  echo Please install WSL Ubuntu first, then try again.
  pause
  exit /b 1
)

set WSL_DISTRO=Ubuntu-22.04
set PROJECT_DIR=/root/XHS-Product-Insight

wsl.exe -d %WSL_DISTRO% -- bash -lc "cd '%PROJECT_DIR%' && ./scripts/start_backend.sh"

if errorlevel 1 (
  echo.
  echo Backend failed to start. Please check the error message above.
  pause
  exit /b 1
)

endlocal
