@echo off
rem ============================================================
rem  Course & Homework Manager - Windows Launcher
rem  Double-click this file to start the GUI program.
rem  chcp 65001 + PYTHONUTF8 ensure Chinese displays correctly.
rem  NOTE: keep this .bat in the same folder as main.py.
rem ============================================================

rem Switch console to UTF-8 code page so Chinese text is correct
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

rem Always run from the folder where this .bat is located
cd /d "%~dp0"

rem 1) Prefer the Windows "py" launcher (installed by python.org)
where py >nul 2>nul
if %errorlevel%==0 (
    start "CourseManager" /b pyw -3 main.py
    if %errorlevel%==0 goto :eof
    start "CourseManager" /b py -3 main.py
    goto :eof
)

rem 2) Fallback: pythonw (no black console window)
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "CourseManager" /b pythonw main.py
    goto :eof
)

rem 3) Fallback: python (with console window, shows errors if any)
where python >nul 2>nul
if %errorlevel%==0 (
    python main.py
    goto :eof
)

echo [ERROR] Python was not found on this computer.
echo Please install Python 3.8+ from https://www.python.org/downloads/
echo and check "Add Python to PATH" during installation.
pause
