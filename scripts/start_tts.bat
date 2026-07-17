@echo off
REM ============================================================
REM 启动 TTS 服务 (WSL Ubuntu)
REM 用法: scripts\start_tts.bat
REM ============================================================
echo [TTS] Starting VoxCPM TTS Server on WSL Ubuntu...
echo [TTS] Port: 8808, Device: CUDA
echo [TTS] Mode: ultimate cloning
echo [TTS] Reference: ~/baoer.mp3
echo.
wsl.exe -d Ubuntu -- bash -lc "cd ~ && export TORCH_MATMUL_PRECISION=high && python3 /mnt/d/workspace/videoFactory/scripts/tts_server.py --port 8808 --device cuda --reference-wav ~/baoer.mp3"
