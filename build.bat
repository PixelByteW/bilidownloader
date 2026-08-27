@echo off
chcp 65001 >nul
cd /d %~dp0
if not exist ffmpeg\ffmpeg.exe (
    echo [错误] 缺少 ffmpeg\ffmpeg.exe，请先下载静态构建放入 ffmpeg\ 目录
    exit /b 1
)
python -m PyInstaller --noconfirm --clean BiliDownloader.spec
if errorlevel 1 (
    echo [错误] 打包失败
    exit /b 1
)
echo.
echo [完成] 输出文件: dist\BiliDownloader.exe
pause