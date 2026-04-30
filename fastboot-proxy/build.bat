@echo off
:: Fastboot Proxy build
:: 1. py -m PyInstaller --onefile --name fastboot
:: 2. output: dist/fastboot.exe

set DIR=%~dp0
cd /d %DIR%

echo [build] cleaning...
rmdir /s /q dist 2>nul
rmdir /s /q build 2>nul
del /q fastboot.spec 2>nul

echo [build] compiling...
python -m PyInstaller --onefile --console --name fastboot --distpath dist --workpath build --specpath . fastboot_proxy.py

if %ERRORLEVEL% neq 0 (
    echo [build] FAILED
    exit /b %ERRORLEVEL%
)

echo.
echo ================================================
echo  Done: dist/fastboot.exe
echo.
echo  NEXT:
echo  1. copy dist/fastboot.exe to platform-tools folder
echo  2. rename original fastboot.exe to fastboot_real.exe in same folder
echo  3. data: %%USERPROFILE%%\Documents\fastboot\
echo     - *.log          command log (one line per call)
echo     - backup/flash/  flash source files
echo     - backup/boot/   boot image files
echo     - backup/update/ update zip files
echo ================================================
