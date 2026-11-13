@echo off
rem Registers this folder's POBG server in Claude Desktop. Double-click it, or run it from a terminal.
rem Options are passed on, for example: install_claude_desktop.bat --remove
echo Quit Claude Desktop completely before you continue ^(also from the system tray^).
echo.
where uv >nul 2>nul
if errorlevel 1 (
    echo uv was not found. Install it first, then run this again:
    echo https://docs.astral.sh/uv/getting-started/installation/
    echo.
    pause
    exit /b 1
)
uv run --frozen --no-dev --directory "%~dp0." python -m src.tools.install_desktop %*
set POBG_RESULT=%errorlevel%
echo.
pause
exit /b %POBG_RESULT%
