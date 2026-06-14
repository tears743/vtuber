@echo off
REM ============================================================
REM Phase 3: Overlay 渲染 (Remotion 透明弹幕/卡片层)
REM 用法: scripts\step_overlay.bat [日期]
REM ============================================================
setlocal
set DATE=%1
if "%DATE%"=="" for /f %%a in ('python -c "from datetime import datetime;print(datetime.now().strftime('%%Y-%%m-%%d'))"') do set DATE=%%a

echo [STEP] Overlay Render - Date: %DATE%
python -m agents.renderer.run_render --date %DATE% --step render
if errorlevel 1 (
    echo [ERROR] Overlay render failed!
    exit /b 1
)
echo [STEP] Overlay render done.
