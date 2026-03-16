@echo off
set "SHORTCUT=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\ReaStream Bridge.lnk"
if exist "%SHORTCUT%" (
    del "%SHORTCUT%"
    echo Startup shortcut removed.
) else (
    echo No startup shortcut found.
)
pause
