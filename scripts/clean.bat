@echo off
REM ============================================================
REM 清理产物 (保留 collected 和 media 原始数据)
REM 用法: scripts\clean.bat [日期] [--all]
REM   --all 清除所有产物（含 selected/scripts）
REM   默认只清除渲染产物（保留 selected/scripts）
REM ============================================================
setlocal
set DATE=%1
if "%DATE%"=="" for /f %%a in ('python -c "from datetime import datetime;print(datetime.now().strftime('%%Y-%%m-%%d'))"') do set DATE=%%a

set CLEAN_ALL=0
if "%2"=="--all" set CLEAN_ALL=1

set DATA_DIR=data\%DATE%

echo [CLEAN] Date: %DATE%
echo [CLEAN] Dir: %DATA_DIR%
echo.

REM 渲染产物
echo [CLEAN] Removing render outputs...
if exist "%DATA_DIR%\audio" rmdir /s /q "%DATA_DIR%\audio"
if exist "%DATA_DIR%\scripts_aligned" rmdir /s /q "%DATA_DIR%\scripts_aligned"
if exist "%DATA_DIR%\overlay" rmdir /s /q "%DATA_DIR%\overlay"
if exist "%DATA_DIR%\visual" rmdir /s /q "%DATA_DIR%\visual"
if exist "%DATA_DIR%\visuals" rmdir /s /q "%DATA_DIR%\visuals"
if exist "%DATA_DIR%\live2d" rmdir /s /q "%DATA_DIR%\live2d"
if exist "%DATA_DIR%\output" rmdir /s /q "%DATA_DIR%\output"
if exist "%DATA_DIR%\final" rmdir /s /q "%DATA_DIR%\final"

if %CLEAN_ALL%==1 (
    echo [CLEAN] Removing scripts + selected...
    if exist "%DATA_DIR%\scripts" rmdir /s /q "%DATA_DIR%\scripts"
    if exist "%DATA_DIR%\selected" rmdir /s /q "%DATA_DIR%\selected"
)

echo [CLEAN] Done. Preserved: collected/, media/
