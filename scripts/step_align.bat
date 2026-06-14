@echo off
REM ============================================================
REM Phase 2: Timeline 对齐 (根据实际 TTS 音频时长调整时间轴)
REM 用法: scripts\step_align.bat [日期]
REM ============================================================
setlocal
set DATE=%1
if "%DATE%"=="" for /f %%a in ('python -c "from datetime import datetime;print(datetime.now().strftime('%%Y-%%m-%%d'))"') do set DATE=%%a

echo [STEP] Align - Date: %DATE%
python -m agents.renderer.run_render --date %DATE% --step align
if errorlevel 1 (
    echo [ERROR] Align failed!
    exit /b 1
)
echo [STEP] Align done.
