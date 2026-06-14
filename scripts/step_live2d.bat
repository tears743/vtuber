@echo off
REM ============================================================
REM Phase 5: Live2D 渲染 (角色动画 + 口型同步)
REM 用法: scripts\step_live2d.bat [日期]
REM ============================================================
setlocal
set DATE=%1
if "%DATE%"=="" for /f %%a in ('python -c "from datetime import datetime;print(datetime.now().strftime('%%Y-%%m-%%d'))"') do set DATE=%%a

echo [STEP] Live2D Render - Date: %DATE%
python -m agents.renderer.run_render --date %DATE% --step live2d
if errorlevel 1 (
    echo [ERROR] Live2D render failed!
    exit /b 1
)
echo [STEP] Live2D render done.
