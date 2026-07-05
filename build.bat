@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM ============================================================
REM PhysChem-DigitizerP Windows 打包脚本
REM 用法：双击运行或在命令行执行 build.bat
REM 输出：dist\PhysChem-DigitizerP\PhysChem-DigitizerP.exe
REM ============================================================

echo.
echo ============================================================
echo   PhysChem-DigitizerP 打包工具
echo ============================================================
echo.

REM 切换到脚本所在目录（项目根目录）
cd /d "%~dp0"

REM 1. 检查 Python
echo [1/5] 检查 Python 环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.8+ 并添加到 PATH
    pause
    exit /b 1
)
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo   Python 版本: %PYVER%

REM 2. 检查项目依赖
echo.
echo [2/5] 检查项目依赖...
python -c "import PyQt6, serial, matplotlib, numpy" >nul 2>&1
if errorlevel 1 (
    echo [警告] 缺少必需依赖，尝试自动安装...
    pip install PyQt6^>=6.4.0 pyserial^>=3.5 matplotlib^>=3.5.0 numpy^>=1.21.0
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请手动执行：pip install PyQt6 pyserial matplotlib numpy
        pause
        exit /b 1
    )
)
echo   项目依赖检查通过

REM 3. 检查 PyInstaller
echo.
echo [3/5] 检查 PyInstaller...
python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo   PyInstaller 未安装，正在安装...
    pip install pyinstaller
    if errorlevel 1 (
        echo [错误] PyInstaller 安装失败
        pause
        exit /b 1
    )
)
echo   PyInstaller 已就绪

REM 4. 检查可选依赖 bleak
echo.
echo [4/5] 检查可选依赖（BLE）...
python -c "import bleak" >nul 2>&1
if errorlevel 1 (
    echo   bleak 未安装，BLE 功能将不可用（其他功能不受影响）
    echo   如需 BLE：pip install bleak
) else (
    echo   bleak 已安装，BLE 功能将被打包
)

REM 5. 清理旧文件并打包
echo.
echo [5/5] 开始打包...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

pyinstaller physchem.spec --noconfirm
if errorlevel 1 (
    echo.
    echo [错误] 打包失败，请检查上方错误信息
    pause
    exit /b 1
)

REM 完成
echo.
echo ============================================================
echo   打包成功！
echo ============================================================
echo.
echo   输出目录: dist\PhysChem-DigitizerP\
echo   可执行文件: dist\PhysChem-DigitizerP\PhysChem-DigitizerP.exe
echo.
echo   使用说明:
echo   1. 将整个 dist\PhysChem-DigitizerP 文件夹复制到目标机器
echo   2. 双击 PhysChem-DigitizerP.exe 运行
echo   3. 首次运行会在 EXE 同级目录生成 sensor_config.json
echo.
echo   注意:
echo   - 不要删除 EXE 同级目录下的 _internal 文件夹（运行时依赖）
echo   - 如需分发，可压缩整个 PhysChem-DigitizerP 文件夹
echo   - 传感器代码/ 已打包到 _internal\传感器代码\，可热更新 .py 文件
echo.
pause
