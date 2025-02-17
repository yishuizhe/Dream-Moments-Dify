@echo off
REM 设置代码页为 GBK
chcp 936 >nul
title My Dream Moments 启动器

cls
echo ====================================
echo        My Dream Moments 启动器
echo ====================================
echo.
echo ╔═══════════════════════════════════╗
echo ║      My Dream Moments - AI Chat   ║
echo ║      Created with Heart by umaru  ║
echo ╚═══════════════════════════════════╝
echo.

REM 创建桌面快捷方式
set "SCRIPT_PATH=%~f0"
set "DESKTOP_PATH=%USERPROFILE%\Desktop"
set "SHORTCUT_PATH=%DESKTOP_PATH%\My Dream Moments.lnk"

dir "%SHORTCUT_PATH%" >nul 2>nul
if errorlevel 1 (
    choice /c yn /m "是否要在桌面创建快捷方式"
    if errorlevel 2 goto SKIP_SHORTCUT
    if errorlevel 1 (
        echo 正在创建桌面快捷方式...
        powershell "$WS = New-Object -ComObject WScript.Shell; $SC = $WS.CreateShortcut('%SHORTCUT_PATH%'); $SC.TargetPath = '%SCRIPT_PATH%'; $SC.WorkingDirectory = '%~dp0'; $SC.Save()"
        echo 快捷方式创建完成！
        echo.
    )
)
:SKIP_SHORTCUT

REM 设置环境变量以支持中文路径
set PYTHONIOENCODING=utf8
set JAVA_TOOL_OPTIONS=-Dfile.encoding=UTF-8

REM 检查 Python 环境
where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未检测到 Python 环境！
    echo 请安装 Python 并确保将其添加到系统环境变量中。
    echo 按任意键退出...
    pause >nul
    exit /b 1
)

REM 检查 Python 版本
python --version | findstr "3." >nul
if errorlevel 1 (
    echo [错误] Python 版本不兼容！
    echo 请安装 Python 3.x 版本。
    echo 按任意键退出...
    pause >nul
    exit /b 1
)

echo 正在检查必要的Python模块...
python -c "import pyautogui" 2>nul
if errorlevel 1 (
    echo 正在安装 pyautogui 模块...
    pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org --trusted-host mirrors.aliyun.com pyautogui -i http://mirrors.aliyun.com/pypi/simple/
)

python -c "import streamlit" 2>nul
if errorlevel 1 (
    echo 正在安装 streamlit 模块...
    pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org --trusted-host mirrors.aliyun.com streamlit -i http://mirrors.aliyun.com/pypi/simple/
)

python -c "import sqlalchemy" 2>nul
if errorlevel 1 (
    echo 正在安装 sqlalchemy 模块...
    pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org --trusted-host mirrors.aliyun.com sqlalchemy -i http://mirrors.aliyun.com/pypi/simple/
)

REM 修改依赖安装部分
echo 正在检查并安装必要的依赖...
if exist "requirements.txt" (
    echo [安装] 正在从 requirements.txt 安装依赖...
    pip install --no-warn-script-location --disable-pip-version-check ^
        --trusted-host pypi.org ^
        --trusted-host files.pythonhosted.org ^
        --trusted-host mirrors.aliyun.com ^
        -r requirements.txt -i http://mirrors.aliyun.com/pypi/simple/
    if errorlevel 1 (
        echo [错误] 依赖安装失败！
        echo 请检查网络连接或以管理员身份运行。
        choice /c yn /m "是否继续运行"
        if errorlevel 2 exit /b 1
    )
) else (
    echo [错误] 未找到 requirements.txt 文件！
    echo 请确保该文件存在于当前目录。
    pause
    exit /b 1
)

echo [安装] 检查 pip 更新...
python -m pip install --upgrade pip -i http://mirrors.aliyun.com/pypi/simple/

echo 依赖安装完成！
echo.

REM 修改启动方式
echo 正在启动配置界面...
if not exist "run_config_web.py" (
    echo [错误] 未找到 run_config_web.py 文件！
    echo 请确保该文件存在于当前目录。
    pause
    exit /b 1
)

REM 检查8501端口是否被占用
netstat -ano | findstr ":8501" >nul
if not errorlevel 1 (
    echo [警告] 端口8501已被占用，正在尝试关闭...
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8501"') do (
        taskkill /f /pid %%a >nul 2>nul
    )
    timeout /t 2 /nobreak >nul
)

REM 修改启动方式
echo 正在启动服务...
start http://localhost:8501/
timeout /t 2 /nobreak >nul

REM 使用单独的窗口启动Python程序，这样可以看到错误信息
start "My Dream Moments Config" cmd /c "python run_config_web.py && pause"
timeout /t 5 /nobreak >nul

REM 检查Python进程是否正在运行
tasklist | findstr "python.exe" >nul
if errorlevel 1 (
    echo [错误] 启动失败！Python进程未运行。
    echo 请检查以下几点：
    echo 1. Python是否正确安装
    echo 2. 是否以管理员身份运行
    echo 3. 防火墙是否阻止了程序运行
    pause
    exit /b 1
)

:check_config
echo.
echo ====================================
echo 请在配置完成后继续：
echo ------------------------------------
echo Y = 完成配置，启动主程序
echo N = 继续等待配置
echo ====================================
echo.
choice /c YN /n /m "是否已完成配置？请输入(Y/N): "
if errorlevel 2 goto check_config
if errorlevel 1 (
    taskkill /f /im "python.exe" >nul 2>nul
    echo.
    echo 配置完成，正在启动机器人...
    
    REM 使用新的cmd窗口启动，这样可以看到错误信息
    start "My Dream Moments" cmd /c "python run.py && pause"
    if errorlevel 1 (
        echo [错误] 机器人启动失败！
        echo 请确保 run.py 文件存在且无语法错误。
        pause
        exit /b 1
    )
)

pause