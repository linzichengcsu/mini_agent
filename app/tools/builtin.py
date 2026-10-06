"""内置工具：read_file / run_shell / search_code / ask_user。

每个工具继承 app.tools.base.Tool，只需声明 name / description / parameters
并实现 run()，然后在 app/tools/__init__.py 中注册即可被 Agent 使用。
"""
import fnmatch
import os
import re
import subprocess

from app.core.config import PROJECT_ROOT, settings
from app.tools.base import Tool, ensure_within_allowed


class ReadFileTool(Tool):
    """读取文本文件内容。"""

    name = "read_file"
    description = "读取指定文本文件的内容并返回。适合查看源代码、配置文件、测试用例等。"
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "文件路径，绝对路径或相对于项目根目录的相对路径",
            },
        },
        "required": ["path"],
    }

    def run(self, path: str) -> str:
        try:
            full = ensure_within_allowed(path)
        except PermissionError as e:
            return f"错误：{e}"
        if not os.path.isfile(full):
            return f"错误：文件不存在：{full}"

        try:
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError as e:
            return f"错误：读取文件失败（{e}）"

        original_len = len(content)
        if original_len > settings.READ_FILE_MAX_CHARS:
            content = (
                content[: settings.READ_FILE_MAX_CHARS]
                + f"\n…（内容过长已截断：仅显示前 {settings.READ_FILE_MAX_CHARS} 字符，共 {original_len} 字符）"
            )
        return f"【文件 {full}（共 {original_len} 字符）】\n{content}"


class RunShellTool(Tool):
    """在项目目录下执行 shell 命令（带禁止命令黑名单）。"""

    name = "run_shell"
    description = (
        "在项目目录下执行一条 shell 命令并返回输出。"
        "Windows 上使用 cmd 语法（如 dir、python --version），"
        "Linux/macOS 上使用 bash 语法（如 ls、pwd）。"
        "注意：该工具可以执行任意命令，删除、格式化、关机、杀进程、提权等"
        "危险命令会被安全策略直接拦截，请只执行安全、只读或明确必要的操作。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的 shell 命令"},
            "workdir": {
                "type": "string",
                "description": "可选，命令的工作目录，默认项目根目录",
            },
        },
        "required": ["command"],
    }

    # =====================================================================
    # 安全策略：禁止执行的命令（想调整黑白名单，直接改下面两个属性即可）
    # =====================================================================

    # 1) 命令名黑名单：匹配命令的第一个 token（不区分大小写，自动忽略
    #    包装前缀 / 路径 / .exe 后缀），覆盖删除、格式化、关机、杀进程、
    #    改权限、提权等高风险命令。
    FORBIDDEN_COMMANDS = {
        # 删除类（Unix 与 Windows）
        "rm", "rmdir", "rd", "del", "erase", "unlink",
        # PowerShell 删除命令及其别名
        "remove-item", "ri",
        # 格式化 / 磁盘 / 分区操作
        "format", "fdisk", "diskpart", "mkfs", "mke2fs", "parted", "gdisk", "sfdisk", "dd",
        # 系统电源控制
        "shutdown", "reboot", "halt", "poweroff", "init", "telinit",
        # 进程强制终止
        "kill", "pkill", "killall", "taskkill", "tskill",
        # 权限 / 属主修改
        "chmod", "chown", "chgrp",
        # 提权
        "sudo", "su", "doas",
        # Windows 磁盘擦除 / 加密
        "cipher",
    }

    # 2) 危险模式正则：对整个命令做匹配，兜底"命令名黑名单"覆盖不到的场景
    #    （如 powershell -Command "Remove-Item ..."、rm -rf 位于分隔符之后等）。
    #    注意写紧边界条件，避免误伤合法命令（如 echo rm -rf）。
    FORBIDDEN_PATTERNS = (
        r"(?:^|[;&|]{1,2})\s*rm\s+-[rf]",        # rm -r / rm -f / rm -rf 组合删除
        r"\bRemove-Item\b",                      # PowerShell 删除命令
        r"\breg\s+delete\b",                     # 注册表删除
        r"\bsc\s+delete\b",                      # 服务删除
        # 下载后直接管道执行（curl xxx | sh 等）
        r"\b(?:curl|wget|iwr|Invoke-WebRequest)\b[^|;&]*[|;&]\s*(?:sh|bash|zsh|pwsh|powershell)\b",
    )

    # 3) 常见命令包装前缀：检查时先剥离，再提取真正的命令名
    _WRAPPER_PREFIX_RE = re.compile(
        r"^(?:"
        r"(?:cmd(?:\.exe)?\s+[/-][ck]\s+)"                        # cmd /c、cmd /k
        r"|(?:powershell(?:\.exe)?|pwsh(?:\.exe)?)\s+(?:-command|-c)\s+[\"']?"
        r"|(?:bash|sh|zsh|dash)\s+-c\s+[\"']?"                    # bash -c
        r")",
        re.IGNORECASE,
    )

    def run(self, command: str, workdir: str = "") -> str:
        # ---- 安全检查：命中禁止列表则拒绝执行，不进入 subprocess ----
        blocked, reason = self._check_forbidden(command)
        if blocked:
            return (
                f"错误：命令被安全策略禁止执行：{command}\n"
                f"原因：{reason}。\n"
                f"请改用只读、安全的命令（如查看目录、运行测试、读取文件）完成当前任务。"
            )

        try:
            cwd = ensure_within_allowed(workdir) if workdir else PROJECT_ROOT
        except PermissionError as e:
            return f"错误：{e}"

        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=settings.SHELL_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return f"错误：命令执行超时（>{settings.SHELL_TIMEOUT}s），已终止：{command}"
        except OSError as e:
            return f"错误：无法执行命令（{e}）"

        output = (proc.stdout or "") + (proc.stderr or "")
        if len(output) > settings.SHELL_MAX_OUTPUT:
            output = (
                output[: settings.SHELL_MAX_OUTPUT]
                + f"\n…（输出过长，仅显示前 {settings.SHELL_MAX_OUTPUT} 字符）"
            )
        return (
            f"【命令】{command}\n"
            f"【工作目录】{cwd}\n"
            f"【退出码】{proc.returncode}\n"
            f"【输出】\n{output}"
        )

    def _check_forbidden(self, command: str):
        """检查命令是否命中禁止列表。返回 (是否禁止, 原因)。"""
        name = self._command_name(command)
        if name in self.FORBIDDEN_COMMANDS:
            return True, f"命令「{name}」在禁止命令列表中"
        for pattern in self.FORBIDDEN_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return True, f"命令命中危险模式：{pattern}"
        return False, ""

    @classmethod
    def _command_name(cls, command: str) -> str:
        """提取命令的第一个 token 作为命令名。

        依次剥离常见的包装前缀（cmd /c、powershell -Command、bash -c 等），
        再取第一个 token，并去掉可能的引号、路径与 .exe/.bat 等扩展名，
        最后统一小写。例如：
          "rm -rf /tmp/x"                      -> "rm"
          "cmd /c del /f x"                    -> "del"
          "powershell -Command Remove-Item x"  -> "remove-item"
          "C:\\Windows\\System32\\DEL.EXE /q"  -> "del"
          "echo hello"                         -> "echo"
        """
        stripped = cls._WRAPPER_PREFIX_RE.sub("", command.strip(), count=1)
        match = re.match(r'\s*(?:"([^"]*)"|\'([^\']*)\'|(\S+))', stripped)
        token = (match.group(1) or match.group(2) or match.group(3)) if match else ""
        base = os.path.basename(token)
        if base.lower().endswith((".exe", ".bat", ".cmd", ".com", ".ps1")):
            base = os.path.splitext(base)[0]
        return base.lower()


class SearchCodeTool(Tool):
    """在项目中按正则表达式搜索代码。"""

    name = "search_code"
    description = (
        "在项目代码中按正则表达式搜索文本，返回「文件:行号: 内容」列表。"
        "自动跳过 .git、node_modules、__pycache__、.venv 等无关目录。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "正则表达式或普通文本，如 'def main' 或 'TODO|FIXME'",
            },
            "path": {
                "type": "string",
                "description": "可选，搜索起点目录，默认项目根目录",
            },
            "include": {
                "type": "string",
                "description": "可选，文件名过滤（fnmatch 风格），逗号分隔，如 '*.py' 或 '*.py,*.js'",
            },
        },
        "required": ["pattern"],
    }

    # 搜索时跳过的目录名
    SKIP_DIRS = {
        ".git", "node_modules", "__pycache__", ".venv", "venv", ".idea",
        "dist", "build", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    }

    def run(self, pattern: str, path: str = "", include: str = "") -> str:
        try:
            root = ensure_within_allowed(path or PROJECT_ROOT)
        except PermissionError as e:
            return f"错误：{e}"
        if not os.path.isdir(root):
            return f"错误：目录不存在：{root}"

        try:
            regex = re.compile(pattern)
        except re.error as e:
            return f"错误：正则表达式无效（{e}）"

        include_patterns = [p.strip() for p in include.split(",") if p.strip()]

        hits = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in self.SKIP_DIRS]
            for fname in sorted(filenames):
                if include_patterns and not any(
                    fnmatch.fnmatch(fname, p) for p in include_patterns
                ):
                    continue
                fpath = os.path.join(dirpath, fname)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                        for lineno, line in enumerate(f, 1):
                            if regex.search(line):
                                hits.append(f"{fpath}:{lineno}: {line.rstrip()[:200]}")
                                if len(hits) >= settings.SEARCH_MAX_RESULTS:
                                    return self._format(hits, pattern, root, truncated=True)
                except OSError:
                    continue
        return self._format(hits, pattern, root, truncated=False)

    @staticmethod
    def _format(hits, pattern: str, root: str, truncated: bool) -> str:
        if not hits:
            return f"未在 {root} 中找到匹配「{pattern}」的内容。"
        body = "\n".join(hits)
        if truncated:
            body += f"\n…（结果超过 {settings.SEARCH_MAX_RESULTS} 条，已截断）"
        return f"【搜索「{pattern}」于 {root}，共 {len(hits)} 条结果】\n{body}"


class AskUserTool(Tool):
    """向用户提问，等待回答。"""

    name = "ask_user"
    description = (
        "向用户提出一个问题并等待其回答。当需求不明确、信息不足、"
        "或需要用户做决策时使用，避免在不确定的情况下猜测。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "要向用户提出的问题",
            },
        },
        "required": ["question"],
    }

    def run(self, question: str) -> str:
        # 提示信息用纯文本（避免 emoji 在 Windows GBK 控制台下编码崩溃）
        print(f"\n[助手需要向你确认] {question}", flush=True)
        answer = input("你的回答: ").strip()
        if not answer:
            answer = "（用户未输入内容）"
        return f"用户回答：{answer}"
