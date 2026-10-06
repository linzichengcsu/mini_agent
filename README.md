# mini_agent

基于 DeepSeek 的命令行代码审查助手（AI 智能体），**支持工具调用（Tool Calling）**。

智能体不仅可以对话，还能主动使用工具完成实际工作：读取文件、执行命令、搜索代码、向用户提问。模型（DeepSeek）在回答过程中按需决定调用哪些工具，拿到工具结果后再继续思考，直到给出最终回复。

## 快速开始

```bash
# 1. 安装依赖（Python 3.10+）
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt

# 2. 配置 API Key（在项目根目录 .env 中设置）
#    DEEPSEEK_API_KEY=sk-xxxxxxxx

# 3. 运行
python main.py

# 4. 运行测试（全量）
./run_tests.ps1          # Windows PowerShell
python run_tests.py      # 任意环境
```

运行后输入自然语言即可。例如：
- `帮我看看 main.py 里有什么问题` → 智能体会自动调用 `read_file` 读取文件再审查；
- `运行一下测试看看` → 智能体会调用 `run_shell` 执行测试命令；
- `这个项目里用到 openai 的地方都有哪些` → 智能体会调用 `search_code` 搜索；
- `帮我审查代码，但先告诉我你打算从哪几个方面看` → 智能体会调用 `ask_user` 向你确认。

## 项目结构

```
mini_agent/
├── main.py                    # 入口（转发到 app.main）
├── serve.py                   # ★ API 服务入口（--mode http | stdio），供外部程序（如 Java）调用
├── app/
│   ├── main.py                # Agent 主循环：对话 + 工具调用循环（组合根）
│   ├── core/
│   │   └── config.py          # 全部可调参数（模型、上下文、工具、系统提示词）
│   ├── services/
│   │   ├── context.py         # 上下文窗口限制 + 摘要压缩（按轮分组，保护工具调用对）
│   │   └── token_utils.py     # token 估算（本地，无需网络）
│   ├── server/                # ★ API 服务层（AgentService 内核 + 两种传输协议）
│   │   ├── service.py         #   AgentService：会话管理 / 对话 / 直接执行工具
│   │   ├── http_api.py        #   HTTP JSON API（标准库实现，零依赖）
│   │   └── stdio_rpc.py       #   stdin/stdout JSON-RPC 子进程协议
│   └── tools/                 # ★ 工具层（新增工具主要改这里）
│       ├── base.py            # Tool 基类 + ToolRegistry + 路径安全检查
│       ├── builtin.py         # 四个内置工具实现
│       └── __init__.py        # 创建全局 registry 并注册内置工具
├── java/                      # ★ Java 客户端（零第三方依赖，JDK 11+）
│   ├── src/com/miniagent/client/   # Json / MiniAgentClient(HTTP) / AgentProcessClient(stdio) / Demo
│   └── README.md                    # Java 端使用说明
└── tests/                     # unittest 测试（全程 mock，不发真实请求）
```

## 工具调用是如何工作的

每个用户回合，主循环会运行最多 `MAX_TOOL_ROUNDS` 轮"模型 ⇄ 工具"循环：

1. 把全部工具声明（`registry.schemas()`，即 OpenAI `tools` 参数）随对话消息一起发给模型；
2. 若模型返回 `tool_calls`（它想要调用工具）：
   - 把模型的工具调用请求（assistant 消息）追加进对话；
   - 对每个工具调用，用 `registry.execute(name, arguments)` 执行对应工具；
   - 把工具结果作为 `role: "tool"` 消息追加回对话；
   - 回到第 1 步，让模型基于工具结果继续；
3. 若模型直接返回文本 → 该回合结束，把最终回复展示给用户。

> 关键代码位置：`app/main.py` 的 `run_agent()` 内层 for 循环就是这套协议；`app/tools/__init__.py` 的 `registry` 是执行入口。工具执行的任何错误都会被转成文本返回给模型，让模型自行修正，不会中断对话。

## 内置工具

| 工具名 | 作用 | 主要参数 |
| --- | --- | --- |
| `read_file` | 读取文本文件内容 | `path`（必填） |
| `run_shell` | 在项目目录执行 shell 命令（内置禁止命令黑名单） | `command`（必填）、`workdir`（可选） |
| `search_code` | 按正则搜索代码，返回 `文件:行号: 内容` | `pattern`（必填）、`path`、`include`（可选） |
| `ask_user` | 向用户提问并等待回答 | `question`（必填） |

`read_file` / `search_code` / `run_shell(workdir)` 只能访问 `settings.TOOLS_ALLOWED_DIRS`（默认项目根目录）内的路径，越界会被拒绝。

### run_shell 的禁止命令黑名单

`run_shell` 在源码内置了安全拦截（`app/tools/builtin.py` 的 `RunShellTool`），命中以下任一条件即**拒绝执行**，不进入 `subprocess`：

- **命令名黑名单** `FORBIDDEN_COMMANDS`：匹配命令的第一个 token（不区分大小写，自动忽略 `cmd /c`、`powershell -Command`、`bash -c` 等包装前缀、路径与 `.exe` 后缀）。覆盖：删除类（`rm`/`del`/`rd`/`erase`/`Remove-Item` 等）、格式化/磁盘操作（`format`/`diskpart`/`mkfs`/`dd` 等）、关机重启（`shutdown`/`reboot` 等）、杀进程（`kill`/`taskkill` 等）、改权限（`chmod`/`chown`）、提权（`sudo`/`su`）等。
- **危险模式正则** `FORBIDDEN_PATTERNS`：兜底命令名覆盖不到的场景，如 `rm -rf` 出现在分隔符之后（`cd /tmp && rm -rf x`）、`curl xxx | sh` 下载后直接执行、`reg delete` 等。

想调整拦截规则，直接编辑 `RunShellTool` 的 `FORBIDDEN_COMMANDS`（集合）与 `FORBIDDEN_PATTERNS`（正则元组）即可，无需改动其它代码。被拦截的命令会以"错误：命令被安全策略禁止执行"返回给模型，由模型改用安全命令。

## 如何添加新工具（重点）

新增一个工具只需 **两个步骤**，主循环与模型交互逻辑**无需任何改动**。

### 步骤 1：实现工具类

在 `app/tools/builtin.py` 里新增一个类，继承 `Tool`，覆写四个字段：

- `name` —— 工具名（模型据此调用，建议小写、下划线分隔）；
- `description` —— 告诉模型"这个工具能做什么、什么时候用"。**写得越清楚，模型越会正确使用**；
- `parameters` —— JSON Schema，描述工具参数（类型、是否必填、含义）；
- `run(**kwargs)` —— 真正的执行逻辑，**必须返回字符串**（成功结果或错误信息）。

下面是一个完整的示例——新增一个 `web_search`（联网搜索）工具：

```python
# app/tools/builtin.py 中追加：

class WebSearchTool(Tool):
    name = "web_search"
    description = "搜索互联网，返回与关键词相关的网页标题和链接。需要查最新资料、文档、新闻时使用。"
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词",
            },
            "max_results": {
                "type": "integer",
                "description": "最多返回几条结果，默认 5",
            },
        },
        "required": ["query"],
    }

    def run(self, query: str, max_results: int = 5) -> str:
        # 在这里调用真实的搜索 API，把结果整理成文本返回
        results = search_the_web(query, limit=max_results)  # 伪代码
        if not results:
            return f"未找到与「{query}」相关的结果。"
        lines = [f"{i+1}. {r['title']}\n   {r['url']}" for i, r in enumerate(results)]
        return f"【搜索「{query}」，共 {len(results)} 条结果】\n" + "\n".join(lines)
```

### 步骤 2：注册

在 `app/tools/__init__.py` 里 import 并注册：

```python
# app/tools/__init__.py
from app.tools.builtin import (
    AskUserTool,
    ReadFileTool,
    RunShellTool,
    SearchCodeTool,
    WebSearchTool,          # 新增
)

registry = ToolRegistry()
registry.register(ReadFileTool())
registry.register(RunShellTool())
registry.register(SearchCodeTool())
registry.register(AskUserTool())
registry.register(WebSearchTool())   # 新增
```

完成。重启 `python main.py` 后模型即可使用新工具。**仅这两步，其余代码零改动。**

### 步骤 3（可选但推荐）：写测试

在 `tests/test_tools.py` 中为新工具写单元测试（mock 掉网络/外部依赖），
并在 `run_tests.py` 的 `TEST_MODULES` 里确认已包含 `test_tools`（默认已包含）。

### 编写工具的最佳实践

1. **`description` 写清楚"何时用"**：模型靠它决定是否调用，例如"需要查最新信息时使用"比"一个搜索工具"有效得多。
2. **参数用标准 JSON Schema**：`type`、`description`、`required` 都写上，模型生成参数时才不会出错。
3. **`run` 只返回字符串**：无论是正常结果还是错误信息，都以文本返回；**不要抛异常**（若抛了，`ToolRegistry.execute` 会兜底转成错误文本给模型）。
4. **单条消息别太长**：工具结果会进入模型上下文，注意截断（参考内置工具的 `…（内容过长已截断）` 做法）。
5. **安全默认收窄**：涉及文件/命令的工具，记得走 `ensure_within_allowed()` 做路径白名单校验。
6. **多轮调用心智**：模型可能连续调用多个工具、或对同一工具反复调用，工具本身应尽量"无状态、可重复"。

### 其他可选项

- **更新系统提示词**：在 `app/core/config.py` 的 `SYSTEM_PROMPT` 里补充新工具的使用规则，能显著提升模型调用的正确率。
- **独立成文件**：如果工具逻辑较长，可新建 `app/tools/web_search.py`，再在 `__init__.py` 里 import 注册，方式完全一样。

## 把智能体变成可被 Java 调用的服务

智能体除命令行交互外，还可作为**服务**被外部程序（重点：Java）调用。
提供两种传输协议，共享同一套接口：

| 方式 | 启动 | Java 调用 | 适用场景 |
| --- | --- | --- | --- |
| **HTTP JSON API** | `python serve.py`（默认 127.0.0.1:8000） | `java.net.http.HttpClient`（`MiniAgentClient`） | 远程 / 多客户端并发 |
| **stdio JSON-RPC** | Java 自动启动 `python serve.py --mode stdio` | `ProcessBuilder` 子进程（`AgentProcessClient`） | 程序内嵌，无需端口 |

两种方式都不需要安装任何新 Python 依赖（HTTP 服务用标准库 `http.server` 实现）。
Java 客户端零第三方依赖（仅 JDK 11+），编译即用。

### 1. HTTP JSON API（推荐）

```bash
python serve.py                      # 127.0.0.1:8000
python serve.py --port 9000          # 自定义端口
python serve.py --host 0.0.0.0       # 监听所有网卡（注意安全，见下）
```

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/health` | 健康检查：`{status, model, tools, sessions}` |
| `GET` | `/v1/tools` | 服务端可用工具声明（OpenAI JSON Schema 列表） |
| `POST` | `/v1/chat` | 对话。body：`{"message": "…", "session_id"?: "…", "max_rounds"?: n}` |
| `POST` | `/v1/tools/<name>/execute` | **直接执行工具**（绕过模型），body 即参数字典 |
| `POST` | `/v1/sessions/<id>/reset` | 重置指定会话 |

`/v1/chat` 响应示例：

```json
{
  "session_id": "9f2c…",
  "reply": "最终回复",
  "prompt_tokens": 1200,
  "completion_tokens": 300,
  "total_tokens": 1500,
  "cost": 0.0048,
  "tool_calls": [
    {"name": "read_file", "arguments": "{\"path\": \"main.py\"}", "result": "【文件…】…"}
  ]
}
```

要点：
- **多轮对话**：第一次调用拿到 `session_id`，后续请求带上它即可延续上下文（服务端内存保存，超过 `--max-sessions` 个会话时淘汰最旧）。
- **直接执行工具**：Java 可以不走模型、直接调用 `read_file` / `run_shell` / `search_code`，例如
  `POST /v1/tools/read_file/execute`，body `{"path": "main.py"}`。
- **`ask_user` 被移除**：服务端没有"坐在终端前的用户"，`ask_user` 不会出现在
  `/v1/tools` 中，模型在 API 场景下也不会尝试提问，而是基于已有信息自行决策。

### 2. stdio JSON-RPC（子进程协议）

Java 用 `ProcessBuilder` 启动 `python serve.py --mode stdio`，通过标准输入输出
按行交换 JSON，行为类似"本地调用"：

```text
请求（Java → Python stdin）：{"id": 1, "method": "chat", "params": {"message": "你好"}}
响应（Python → Java stdout）：{"id": 1, "result": {"session_id": "…", "reply": "…", ...}}
```

方法：`health` / `list_tools` / `execute_tool` / `chat` / `reset_session`，
参数与 HTTP 端点一一对应。错误返回 `{"id": …, "error": {"code": …, "message": …}}`。

### 3. Java 客户端（开箱即用）

```bash
# 编译（项目根目录）
javac -encoding UTF-8 -d java/out java/src/com/miniagent/client/*.java

# 运行演示（stdio 方式自包含；HTTP 方式需先 python serve.py）
java -Dfile.encoding=UTF-8 -cp java/out com.miniagent.client.Demo ".\.venv\Scripts\python.exe"
```

```java
// 方式一：stdio 子进程（无需先启动服务）
try (AgentProcessClient c = new AgentProcessClient(".venv/Scripts/python.exe", ".", 120_000)) {
    c.chat("请审查 main.py");                       // 新会话
    c.chat("继续", c.chat("再看一眼").sessionId);    // 多轮对话
    c.executeTool("read_file", Map.of("path", "main.py"));
}

// 方式二：HTTP（需先 python serve.py）
try (MiniAgentClient c = new MiniAgentClient("http://127.0.0.1:8000")) {
    MiniAgentClient.ChatResult r = c.chat("请审查 main.py");
    c.executeTool("search_code", Map.of("pattern", "TODO"));
}
```

完整方法说明、返回字段与进阶用法见 [java/README.md](java/README.md)。

### 4. 关于"native 函数"（JNI / JPype 等）的说明

Java 直连 Python 的"真 native"方案（JNI 嵌入 CPython、[JPype](https://jpype.readthedocs.io/)、
JEP、GraalPy）需要在两端维护复杂的桥接代码与构建配置，且跨平台脆弱。对绝大多数
业务场景，**HTTP 或 stdio 子进程协议是更稳、更易维护的"其他方式"**：它们把
"调用智能体"变成一次网络请求/一次进程通信，Java 侧封装成普通方法即可，
Python 侧零侵入（见上）。若确有同进程强耦合需求，可基于本项目把 `app.server.service.AgentService`
包进 JPype/JEP，无需改动内核。

### 5. 安全注意事项（API 模式）

- **默认只绑定 127.0.0.1**。`run_shell` 可执行任意命令，**不要**在无认证的公网
  环境暴露此服务；确需远程访问请先加反向代理 + 鉴权。
- 服务端移除 `ask_user`，`execute_tool` 对 `ask_user` 也返回拒绝。
- 会话保存在内存中，`--max-sessions` 控制上限；重启服务即清空。

## 相关配置项

以下全部在 `app/core/config.py` 的 `Settings` 类中调整：

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `MAX_TOOL_ROUNDS` | `10` | 单次用户请求内模型最多连续发起几轮工具调用（防死循环） |
| `SHELL_TIMEOUT` | `30` | `run_shell` 命令超时（秒） |
| `SHELL_MAX_OUTPUT` | `8000` | `run_shell` 最多返回的输出字符数 |
| `SEARCH_MAX_RESULTS` | `50` | `search_code` 最多返回的匹配行数 |
| `READ_FILE_MAX_CHARS` | `50000` | `read_file` 单次最多返回的字符数 |
| `TOOLS_ALLOWED_DIRS` | `[PROJECT_ROOT]` | 允许访问的目录白名单；置空列表 `[]` 表示不限制（不推荐） |

## 安全注意事项

- **`run_shell` 可以执行任意命令**，是四个工具中风险最高的一个。模型可能被提示词诱导执行危险命令。建议：
  - 保持 `TOOLS_ALLOWED_DIRS` 收窄（它同样限制 `workdir`）；
  - 不要把这套代码直接暴露成公网 API；
  - 在提示词里约束模型"只执行安全、只读或明确必要的操作"（系统提示词已内置）。
- **`ask_user` 会阻塞等待输入**：它通过 `input()` 同步询问用户，仅适合交互式场景。若未来改造为服务端 API，应替换为"挂起请求、等待前端回填"的实现。
- **工具结果进入上下文**：工具输出会占用 token 并计入费用，内置工具已做长度截断。

## 常见问题

**Q：Windows 命令行下中文/emoji 乱码或报 `UnicodeEncodeError`？**
命令行下先执行 `$env:PYTHONIOENCODING="utf-8"`（PowerShell），或在 `run_tests.ps1` 中已自动设置。在 VS Code / PyCharm 终端中通常无需处理。

**Q：模型似乎不会调用工具？**
先确认 `tools` 参数已随请求发出（`app/main.py` 的 `run_agent` 已自动携带 `registry.schemas()`）。其次检查系统提示词是否描述了工具用途（`config.py` 的 `SYSTEM_PROMPT` 已内置）。最后确认每个工具的 `description` 写得足够清楚。

**Q：工具调用报"孤儿 tool 消息"？**
上下文压缩（`app/services/context.py`）已按"用户回合"分组切分，保证 assistant 的工具调用请求与其 `tool` 结果永远成对保留，正常情况下不会出现。若你手动修改了消息列表，注意保持成对。

**Q：如何临时停用某个工具？**
在 `app/tools/__init__.py` 里注释掉对应的 `registry.register(...)` 即可，无需改动其它代码。

## 测试

```bash
./run_tests.ps1              # 全部测试（Windows）
python run_tests.py          # 全部测试（任意环境）
python run_tests.py test_tools   # 只跑工具层测试
```

测试全程使用 mock 客户端，不产生真实 API 请求；`run_shell` 相关用例只执行 `echo` 等无害命令。
