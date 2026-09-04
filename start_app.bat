@echo off
REM ==================================================================
REM   US Real Estate Market Dashboard  -  launcher
REM
REM     start_app.bat                open the dashboard
REM     start_app.bat --port 8600    use a different port
REM
REM   Sets the environment up on first run, and repairs or updates it
REM   automatically whenever requirements.txt has changed.
REM ==================================================================
setlocal EnableExtensions EnableDelayedExpansion
pushd "%~dp0"

set "HERE=%~dp0"
set "VENV=%HERE%.venv"
set "PY=%VENV%\Scripts\python.exe"
set "REQ=%HERE%requirements.txt"
set "STAMP=%VENV%\.requirements.sha256"
set "PORT=8501"

REM pull --port out of the arguments so we can report the right URL
set "ARGS="
:parse_args
if "%~1"=="" goto args_done
if /i "%~1"=="--port" (
    set "PORT=%~2"
    shift & shift & goto parse_args
)
set "ARGS=!ARGS! %1"
shift
goto parse_args
:args_done

if not exist "%HERE%app.py" (
    echo [X] app.py not found.
    echo     Run this script from the folder that contains it.
    goto fail
)

REM ---------- make sure the environment is present and current -----
set "SETUP=0"
if not exist "%PY%"    set "SETUP=1" & set "REASON=no environment yet"
if not exist "%STAMP%" set "SETUP=1" & set "REASON=environment state unknown"

if "!SETUP!"=="0" (
    call :hash "%REQ%" NEWHASH
    set /p OLDHASH=<"%STAMP%"
    if /i not "!NEWHASH!"=="!OLDHASH!" set "SETUP=1" & set "REASON=requirements.txt has changed"
)

if "!SETUP!"=="1" (
    echo.
    echo   Setting up first ^(!REASON!^)...
    echo.
    REM some systems exclude the current directory from the search path,
    REM so always call the sibling script by its full path
    call "%HERE%install.bat" --auto
    if errorlevel 1 (
        echo.
        echo [X] Setup failed. Run install.bat on its own to see why.
        goto fail
    )
)

REM ---------- pick a port that is actually free --------------------
REM Another copy of the dashboard, or anything else sitting on 8501, would
REM otherwise stop the launch dead. Move to the next free port instead.
set "PORTFILE=%TEMP%\_redash_port.txt"
set "CHOSEN=%PORT%"
"%PY%" "%HERE%scripts\find_free_port.py" %PORT% > "%PORTFILE%" 2>nul
if exist "%PORTFILE%" set /p CHOSEN=<"%PORTFILE%"
del "%PORTFILE%" >nul 2>&1
if not defined CHOSEN set "CHOSEN=%PORT%"

if not "%CHOSEN%"=="%PORT%" (
    echo.
    echo   Port %PORT% is already in use - starting on %CHOSEN% instead.
    set "PORT=%CHOSEN%"
)

REM ---------- launch ----------------------------------------------
echo.
echo ==================================================================
echo   Starting the Real Estate Dashboard
echo.
echo   It will open in your browser at  http://localhost:!PORT!
echo   Leave this window open while you use it.
echo   Press Ctrl+C here to stop.
echo ==================================================================
echo.

"%PY%" -m streamlit run "%HERE%app.py" --server.port !PORT! !ARGS!
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo [X] Streamlit exited with code %RC%.
    echo     To choose a port yourself, run:  start_app.bat --port 8600
    goto fail
)

popd
endlocal
exit /b 0

:hash
REM :hash <file> <out-var>   ->  SHA256 of the file, spaces stripped
set "_h="
for /f "skip=1 delims=" %%H in ('certutil -hashfile "%~1" SHA256 2^>nul') do if not defined _h set "_h=%%H"
set "%~2=!_h: =!"
goto :eof

:fail
echo.
pause
popd
endlocal
exit /b 1
