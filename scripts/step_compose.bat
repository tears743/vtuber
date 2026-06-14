@echo off
REM ============================================================
REM Phase 6: Compose 最终合成 (FFmpeg 合并所有层)
REM 用法: scripts\step_compose.bat [日期]
REM ============================================================
setlocal
set DATE=%1
if "%DATE%"=="" for /f %%a in ('python -c "from datetime import datetime;print(datetime.now().strftime('%%Y-%%m-%%d'))"') do set DATE=%%a

echo [STEP] Compose - Date: %DATE%
python -m agents.renderer.run_render --date %DATE% --step compose
if errorlevel 1 (
    echo [ERROR] Compose failed!
    exit /b 1
)
echo [STEP] Compose done.
