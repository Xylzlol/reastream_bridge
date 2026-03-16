@echo off
:: Creates a shortcut in shell:startup so the bridge runs on login.
:: Run this once as Administrator (or regular user).

set "SCRIPT_DIR=%~dp0"
set "TARGET=%SCRIPT_DIR%bridge_tray.pyw"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SHORTCUT=%STARTUP%\ReaStream Bridge.lnk"

:: Find pythonw.exe
for /f "delims=" %%i in ('where pythonw 2^>nul') do set "PYTHONW=%%i"
if "%PYTHONW%"=="" (
    echo ERROR: pythonw.exe not found in PATH.
    echo Make sure Python is installed and added to PATH.
    pause
    exit /b 1
)

:: Create shortcut via PowerShell
powershell -NoProfile -Command ^
  "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%SHORTCUT%'); $s.TargetPath = '%PYTHONW%'; $s.Arguments = '\"%TARGET%\"'; $s.WorkingDirectory = '%SCRIPT_DIR%'; $s.Description = 'ReaStream Bridge - Spotify to FL Studio'; $s.Save()"

if exist "%SHORTCUT%" (
    echo.
    echo SUCCESS: Startup shortcut created!
    echo   Location: %SHORTCUT%
    echo   Target:   pythonw.exe "%TARGET%"
    echo.
    echo The bridge will now start automatically on login.
    echo To remove: delete the shortcut from shell:startup
    echo   or run:  del "%SHORTCUT%"
) else (
    echo ERROR: Failed to create shortcut.
)

echo.
pause
