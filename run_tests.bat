@echo off
rem 一键运行测试（Windows 双击即可运行）。
rem 会自动使用项目虚拟环境中的 Python，并显示结果。

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found: .venv\Scripts\python.exe
    echo Please create it first:  python -m venv .venv
    pause
    exit /b 1
)

set PYTHONIOENCODING=utf-8
.venv\Scripts\python.exe run_tests.py
set code=%errorlevel%

if "%code%"=="0" (
    echo.
    echo [OK] All tests passed.
) else (
    echo.
    echo [FAIL] Some tests failed, see details above.
)
pause
exit /b %code%
