@echo off
REM ============================================================
REM Phase 4: Visual 渲染 (背景层: Remotion组件 + 图片 + 视频片段)
REM 用法: scripts\step_visual.bat [日期]
REM ============================================================
setlocal
set DATE=%1
if "%DATE%"=="" for /f %%a in ('python -c "from datetime import datetime;print(datetime.now().strftime('%%Y-%%m-%%d'))"') do set DATE=%%a

echo [STEP] Visual Render - Date: %DATE%
python -m agents.renderer.run_render --date %DATE% --step visual
if errorlevel 1 (
    echo [ERROR] Visual render failed!
    exit /b 1
)
echo [STEP] Visual render done.
