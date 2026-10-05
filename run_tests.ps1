# 一键运行项目测试（自动使用项目虚拟环境的 Python）
# 用法（在 PowerShell 中，项目根目录）：
#   ./run_tests.ps1              # 运行全部测试
#   ./run_tests.ps1 test_context # 只运行某个测试模块

param(
    [string]$Module = ""
)

# 注意：不要设置 $ErrorActionPreference = "Stop"。
# Python 的 unittest 把测试结果默认写到 stderr，Stop 会把正常的
# stderr 输出误判为 NativeCommandError，导致每次都弹出错误警告。
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Host "未找到虚拟环境 Python：$Python" -ForegroundColor Red
    Write-Host "请先执行：python -m venv .venv 并安装依赖" -ForegroundColor Red
    exit 1
}

$env:PYTHONIOENCODING = "utf-8"

Write-Host "== 使用 Python: $Python" -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan

if ($Module) {
    & $Python (Join-Path $ProjectRoot "run_tests.py") $Module
} else {
    & $Python (Join-Path $ProjectRoot "run_tests.py")
}
$code = $LASTEXITCODE

Write-Host "================================" -ForegroundColor Cyan
if ($code -eq 0) {
    Write-Host "全部测试通过 (OK)" -ForegroundColor Green
} else {
    Write-Host "存在失败用例，请查看上方详情。" -ForegroundColor Red
}
exit $code
