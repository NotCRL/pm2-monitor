@echo off
rem Double-click to start pm2 monitor and open it in your browser (Windows).
rem Needs Python 3.8 or newer: https://www.python.org/downloads/
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 goto usepy
where python >nul 2>nul
if %errorlevel%==0 goto usepython
goto nopython

:usepy
py -3 launch.py
goto done

:usepython
python launch.py
goto done

:nopython
echo.
echo Python 3.8 or newer is needed to run pm2 monitor, and it was not found.
echo Opening the download page: install Python (tick "Add python.exe to PATH"), then double-click this file again.
start "" "https://www.python.org/downloads/"
pause
goto end

:done
if errorlevel 1 pause
:end
