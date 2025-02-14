@echo off
REM 设置代码页为 GBK
chcp 65001
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

REM 检查路径是否包含中文
echo %CD% | findstr /R /C:"[^\x00-\x7F]" >nul
if not errorlevel 1 (
    echo [警告] 当前路径包含中文字符，可能会导致问题！
    echo 当前路径: %CD%
    echo 建议将程序移动到纯英文路径下运行。
    echo.
    choice /c yn /m "是否继续运行"
    if errorlevel 2 exit /b 1
)

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

REM 修改 pip 安装命令，添加信任参数
:install_modules
echo 正在检查必要的 Python 模块...
set modules=pyautogui streamlit sqlalchemy
for %%m in (%modules%) do (
    python -c "import %%m" 2>nul
    if errorlevel 1 (
        echo 正在安装 %%m 模块...
        pip install --no-warn-script-location --disable-pip-version-check ^
            --trusted-host pypi.org ^
            --trusted-host files.pythonhosted.org ^
            --trusted-host mirrors.aliyun.com ^
            %%m -i http://mirrors.aliyun.com/pypi/simple/
        if errorlevel 1 (
            echo [错误] %%m 模块安装失败！
            echo 请以管理员身份运行或手动安装该模块。
            choice /c yn /m "是否继续运行"
            if errorlevel 2 exit /b 1
        )
    )
)

echo 模块检查完成！
echo.

REM 修改启动方式，但保持 Python 使用 UTF-8
echo 正在启动配置界面...
if not exist "run_config_web.py" (
    echo [错误] 未找到 run_config_web.py 文件！
    echo 请确保该文件存在于当前目录。
    pause
    exit /b 1
)

REM 启动 Python 脚本时设置 UTF-8
start http://localhost:8501/
start /b cmd /c "set PYTHONIOENCODING=utf8 && python run_config_web.py"
if errorlevel 1 (
    echo [错误] 配置界面启动失败！
    echo 请检查 run_config_web.py 是否有语法错误。
    pause
    exit /b 1
)

echo 正在等待配置界面启动...
timeout /t 5 /nobreak >nul

:check_config
echo.
echo 是否已完成配置修改？(Y/N)
set /p CONFIG_DONE=": "
if /i "%CONFIG_DONE%"=="Y" (
    taskkill /f /im python.exe >nul 2>nul
    echo.
    echo 配置完成，正在启动机器人...
    cmd /c "set PYTHONIOENCODING=utf8 && python run.py"
    if errorlevel 1 (
        echo [31m[错误][0m 机器人启动失败！
        echo 请确保 run.py 文件存在且无语法错误。
        pause
        exit /b 1
    )
) else if /i "%CONFIG_DONE%"=="N" (
    goto check_config
) else (
    echo 无效的输入，请输入 Y 或 N
    goto check_config
)

pause
