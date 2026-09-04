@echo off
REM ==================================================================
REM   US Real Estate Market Dashboard  -  install / update
REM
REM     install.bat            create the environment, or update it
REM     install.bat --dev      also install the test dependencies
REM     install.bat --clean    rebuild the environment from scratch
REM
REM   Safe to re-run at any time. Every run upgrades the installed
REM   packages to the newest versions allowed by requirements.txt,
REM   so this doubles as the updater.
REM ==================================================================
setlocal EnableExtensions EnableDelayedExpansion
pushd "%~dp0"

set "HERE=%~dp0"
set "VENV=%HERE%.venv"
set "PY=%VENV%\Scripts\python.exe"
set "REQ=%HERE%requirements.txt"
set "REQDEV=%HERE%requirements-dev.txt"
set "STAMP=%VENV%\.requirements.sha256"
set "MINPY=3.10"
set "AUTO=0"
set "DEV=0"
set "CLEAN=0"

:parse_args
if "%~1"==""           goto args_done
if /i "%~1"=="--auto"  set "AUTO=1"  & shift & goto parse_args
if /i "%~1"=="--dev"   set "DEV=1"   & shift & goto parse_args
if /i "%~1"=="--clean" set "CLEAN=1" & shift & goto parse_args
if /i "%~1"=="--help"  goto usage
if /i "%~1"=="-h"      goto usage
if /i "%~1"=="/?"      goto usage
echo Unknown option: %~1
echo.
goto usage
:args_done

echo.
echo ==================================================================
echo   Real Estate Dashboard  -  environment setup
echo ==================================================================
echo.

if not exist "%REQ%" (
    echo [X] %REQ% not found.
    echo     Run this script from the folder that contains app.py.
    goto fail
)

REM ---------- 1. locate a suitable Python -------------------------
echo [1/5] Locating Python %MINPY% or newer...
set "BOOTSTRAP="
call :try_python "py -3"
if not defined BOOTSTRAP call :try_python "python"
if not defined BOOTSTRAP call :try_python "python3"
if not defined BOOTSTRAP goto no_python

for /f "delims=" %%V in ('%BOOTSTRAP% -c "import sys;print(sys.version.split()[0])" 2^>nul') do set "PYVER=%%V"
echo       found Python !PYVER!  ^(via "%BOOTSTRAP%"^)

REM ---------- 2. create or validate the virtual environment --------
if "%CLEAN%"=="1" if exist "%VENV%" (
    echo [2/5] --clean: removing the existing environment...
    rmdir /s /q "%VENV%"
)

set "NEEDVENV=0"
if not exist "%PY%" set "NEEDVENV=1"
if exist "%PY%" (
    "%PY%" -c "import sys" >nul 2>&1
    if errorlevel 1 (
        echo       existing environment is broken, rebuilding it...
        rmdir /s /q "%VENV%"
        set "NEEDVENV=1"
    )
)

if "!NEEDVENV!"=="1" (
    echo [2/5] Creating the virtual environment in %VENV% ...
    %BOOTSTRAP% -m venv "%VENV%"
    if errorlevel 1 (
        echo [X] Could not create the virtual environment.
        goto fail
    )
) else (
    echo [2/5] Virtual environment already present.
)

REM ---------- 3. upgrade the packaging tools -----------------------
echo [3/5] Updating pip and build tools...
"%PY%" -m pip install --quiet --upgrade --disable-pip-version-check pip setuptools wheel
if errorlevel 1 (
    echo [X] Could not update pip. Check your network or proxy settings.
    goto fail
)

REM ---------- 4. install / upgrade the dependencies ----------------
echo [4/5] Installing and upgrading dependencies from %REQ% ...
echo       ^(this can take a few minutes the first time^)
"%PY%" -m pip install --upgrade --disable-pip-version-check -r "%REQ%"
if errorlevel 1 (
    echo [X] Dependency installation failed. See the output above.
    goto fail
)

if "%DEV%"=="1" if exist "%REQDEV%" (
    echo       installing test dependencies from %REQDEV% ...
    "%PY%" -m pip install --upgrade --disable-pip-version-check -r "%REQDEV%"
    if errorlevel 1 (
        echo [X] Test dependency installation failed.
        goto fail
    )
)

REM ---------- 5. verify the app actually imports -------------------
echo [5/5] Verifying the installation...
"%PY%" -m compileall -q "%HERE%src" "%HERE%app.py" >nul 2>&1
if errorlevel 1 (
    echo [X] The source files failed to compile.
    goto fail
)
"%PY%" -c "import streamlit,pandas,numpy,plotly,pyarrow,requests,truststore" >nul 2>&1
if errorlevel 1 (
    echo.
    echo [!] The packages installed but could not all be imported.
    echo     A dependency may have shipped a breaking release.
    echo     Try rebuilding from scratch:   install.bat --clean
    goto fail
)

REM record which requirements this environment was built from, so
REM start_app.bat can spot an out-of-date environment by itself
call :hash "%REQ%" REQHASH
> "%STAMP%" echo !REQHASH!

REM a quoted executable path confuses for /f, so round-trip via a temp file
set "TMPV=%TEMP%\_redash_ver.txt"
"%PY%" -c "import streamlit;print(streamlit.__version__)" > "%TMPV%" 2>nul
set "SLVER=unknown"
if exist "%TMPV%" set /p SLVER=<"%TMPV%"
del "%TMPV%" >nul 2>&1

echo.
echo ==================================================================
echo   Ready.  Streamlit !SLVER! on Python !PYVER!
echo.
echo   Start the dashboard with:   start_app.bat
echo ==================================================================
echo.
if "%AUTO%"=="0" pause
popd
endlocal
exit /b 0

REM ================== helpers ======================================

:try_python
REM %~1 is a launcher command; sets BOOTSTRAP if it meets the minimum
%~1 -c "import sys;raise SystemExit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
if not errorlevel 1 set "BOOTSTRAP=%~1"
goto :eof

:hash
REM :hash <file> <out-var>   ->  SHA256 of the file, spaces stripped
set "_h="
for /f "skip=1 delims=" %%H in ('certutil -hashfile "%~1" SHA256 2^>nul') do if not defined _h set "_h=%%H"
set "%~2=!_h: =!"
goto :eof

:no_python
echo.
echo [X] No Python %MINPY% or newer was found on this machine.
echo.
echo     Install it from https://www.python.org/downloads/
echo     and tick "Add python.exe to PATH" during setup.
echo     Then run install.bat again.
goto fail

:usage
echo.
echo   install.bat            create the environment, or update it
echo   install.bat --dev      also install the test dependencies
echo   install.bat --clean    rebuild the environment from scratch
echo.
if "%AUTO%"=="0" pause
popd
endlocal
exit /b 0

:fail
echo.
if "%AUTO%"=="0" pause
popd
endlocal
exit /b 1
