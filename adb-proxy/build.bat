@echo off
:: ADB Proxy build
:: 1. py -m PyInstaller --onefile --name adb
:: 2. output: dist/adb.exe

set DIR=%~dp0
cd /d %DIR%

echo [build] cleaning...
rmdir /s /q dist 2>nul
rmdir /s /q build 2>nul
del /q adb.spec 2>nul

echo [build] compiling...
python -m PyInstaller --onefile --console --name adb --distpath dist --workpath build --specpath . adb_proxy.py

if %ERRORLEVEL% neq 0 (
    echo [build] FAILED
    exit /b %ERRORLEVEL%
)

echo.
echo ================================================
echo  Done: dist/adb.exe
echo.
echo  NEXT:
echo  1. copy dist/adb.exe to platform-tools folder
echo  2. rename original adb.exe to adb_real.exe in same folder
echo  3. data: %%USERPROFILE%%\Documents\adb\
echo     - *.log          command log (one line per call)
echo     - backup/push/   push source files
echo     - backup/pull/   pull destination files
echo     - backup/install/ install APK files
echo ================================================