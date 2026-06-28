@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %ERRORLEVEL%==0 (
  set "PYTHON_CMD=py -3"
) else (
  set "PYTHON_CMD=python"
)

%PYTHON_CMD% -m pip install -r requirements-streamlit.txt
if errorlevel 1 (
  echo.
  echo Failed to install requirements. Please check Python and pip.
  pause
  exit /b 1
)

%PYTHON_CMD% -m streamlit run comic_ficp_streamlit_app.py --server.address 127.0.0.1 --server.port 8510
pause
