@echo off
REM ���ô���ҳΪ GBK
chcp 936 >nul
title My Dream Moments ������

cls
echo ====================================
echo        My Dream Moments ������
echo ====================================
echo.
echo �X�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�[
echo �U      My Dream Moments - AI Chat   �U
echo �U      Created with Heart by umaru  �U
echo �^�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�a
echo.

REM ���������ݷ�ʽ
set "SCRIPT_PATH=%~f0"
set "DESKTOP_PATH=%USERPROFILE%\Desktop"
set "SHORTCUT_PATH=%DESKTOP_PATH%\My Dream Moments.lnk"

dir "%SHORTCUT_PATH%" >nul 2>nul
if errorlevel 1 (
    choice /c yn /m "�Ƿ�Ҫ�����洴����ݷ�ʽ"
    if errorlevel 2 goto SKIP_SHORTCUT
    if errorlevel 1 (
        echo ���ڴ��������ݷ�ʽ...
        powershell "$WS = New-Object -ComObject WScript.Shell; $SC = $WS.CreateShortcut('%SHORTCUT_PATH%'); $SC.TargetPath = '%SCRIPT_PATH%'; $SC.WorkingDirectory = '%~dp0'; $SC.Save()"
        echo ��ݷ�ʽ������ɣ�
        echo.
    )
)
:SKIP_SHORTCUT

REM ���û���������֧������·��
set PYTHONIOENCODING=utf8
set JAVA_TOOL_OPTIONS=-Dfile.encoding=UTF-8

REM ��� Python ����
where python >nul 2>nul
if errorlevel 1 (
    echo [����] δ��⵽ Python ������
    echo �밲װ Python ��ȷ��������ӵ�ϵͳ���������С�
    echo ��������˳�...
    pause >nul
    exit /b 1
)

REM ��� Python �汾
python --version | findstr "3." >nul
if errorlevel 1 (
    echo [����] Python �汾�����ݣ�
    echo �밲װ Python 3.x �汾��
    echo ��������˳�...
    pause >nul
    exit /b 1
)

echo ���ڼ���Ҫ��Pythonģ��...
python -c "import pyautogui" 2>nul
if errorlevel 1 (
    echo ���ڰ�װ pyautogui ģ��...
    pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org --trusted-host mirrors.aliyun.com pyautogui -i http://mirrors.aliyun.com/pypi/simple/
)

python -c "import streamlit" 2>nul
if errorlevel 1 (
    echo ���ڰ�װ streamlit ģ��...
    pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org --trusted-host mirrors.aliyun.com streamlit -i http://mirrors.aliyun.com/pypi/simple/
)

python -c "import sqlalchemy" 2>nul
if errorlevel 1 (
    echo ���ڰ�װ sqlalchemy ģ��...
    pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org --trusted-host mirrors.aliyun.com sqlalchemy -i http://mirrors.aliyun.com/pypi/simple/
)

REM �޸�������װ����
echo ���ڼ�鲢��װ��Ҫ������...
if exist "requirements.txt" (
    echo [��װ] ���ڴ� requirements.txt ��װ����...
    pip install --no-warn-script-location --disable-pip-version-check ^
        --trusted-host pypi.org ^
        --trusted-host files.pythonhosted.org ^
        --trusted-host mirrors.aliyun.com ^
        -r requirements.txt -i http://mirrors.aliyun.com/pypi/simple/
    if errorlevel 1 (
        echo [����] ������װʧ�ܣ�
        echo �����������ӻ��Թ���Ա������С�
        choice /c yn /m "�Ƿ��������"
        if errorlevel 2 exit /b 1
    )
) else (
    echo [����] δ�ҵ� requirements.txt �ļ���
    echo ��ȷ�����ļ������ڵ�ǰĿ¼��
    pause
    exit /b 1
)

echo [��װ] ��� pip ����...
python -m pip install --upgrade pip -i http://mirrors.aliyun.com/pypi/simple/

echo ������װ��ɣ�
echo.

REM �޸�������ʽ
echo �����������ý���...
if not exist "run_config_web.py" (
    echo [����] δ�ҵ� run_config_web.py �ļ���
    echo ��ȷ�����ļ������ڵ�ǰĿ¼��
    pause
    exit /b 1
)

REM ���8501�˿��Ƿ�ռ��
netstat -ano | findstr ":8501" >nul
if not errorlevel 1 (
    echo [����] �˿�8501�ѱ�ռ�ã����ڳ��Թر�...
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8501"') do (
        taskkill /f /pid %%a >nul 2>nul
    )
    timeout /t 2 /nobreak >nul
)

REM �޸�������ʽ
echo ������������...
start http://localhost:8501/
timeout /t 2 /nobreak >nul

REM ʹ�õ����Ĵ�������Python�����������Կ���������Ϣ
start "My Dream Moments Config" cmd /c "python run_config_web.py && pause"
timeout /t 5 /nobreak >nul

REM ���Python�����Ƿ���������
tasklist | findstr "python.exe" >nul
if errorlevel 1 (
    echo [����] ����ʧ�ܣ�Python����δ���С�
    echo �������¼��㣺
    echo 1. Python�Ƿ���ȷ��װ
    echo 2. �Ƿ��Թ���Ա�������
    echo 3. ����ǽ�Ƿ���ֹ�˳�������
    pause
    exit /b 1
)

:check_config
echo.
echo ====================================
echo ����������ɺ������
echo ------------------------------------
echo Y = ������ã�����������
echo N = �����ȴ�����
echo ====================================
echo.
choice /c YN /n /m "�Ƿ���������ã�������(Y/N): "
if errorlevel 2 goto check_config
if errorlevel 1 (
    taskkill /f /im "python.exe" >nul 2>nul
    echo.
    echo ������ɣ���������������...
    
    REM ʹ���µ�cmd�����������������Կ���������Ϣ
    start "My Dream Moments" cmd /c "python run.py && pause"
    if errorlevel 1 (
        echo [����] ����������ʧ�ܣ�
        echo ��ȷ�� run.py �ļ����������﷨����
        pause
        exit /b 1
    )
)

pause