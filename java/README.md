# Java 客户端

这里提供了**零第三方依赖**（仅用 JDK 11+ 标准库）的 Java 客户端，用于调用
mini_agent 智能体。两种调用方式二选一：

| 方式 | Java 类 | 前提 | 适用场景 |
| --- | --- | --- | --- |
| **stdio 子进程** | `AgentProcessClient` | 无（Java 自动启动 Python 子进程） | 程序内嵌调用，无需端口/防火墙 |
| **HTTP** | `MiniAgentClient` | 先运行 `python serve.py` | 远程/多客户端并发调用 |

## 目录

```
java/
├── src/com/miniagent/client/
│   ├── Json.java                # 极简 JSON 解析/生成（无第三方库）
│   ├── MiniAgentClient.java     # HTTP JSON API 客户端
│   ├── AgentProcessClient.java  # stdio JSON-RPC 子进程客户端
│   └── Demo.java                # 演示程序（两种方式）
└── README.md
```

## 编译

```bash
# 在项目根目录执行
javac -encoding UTF-8 -d java/out java/src/com/miniagent/client/*.java
```

## 运行演示

```bash
# stdio 方式自包含；HTTP 方式需先启动服务：python serve.py
java -Dfile.encoding=UTF-8 -cp java/out com.miniagent.client.Demo ".\.venv\Scripts\python.exe"
```

> 说明：
> - `Demo` 的第一个参数是 Python 解释器路径（Windows 下推荐
>   `.venv\Scripts\python.exe`）；第二个参数传 `nochat` 可跳过真实调用模型的
>   `chat` 环节（避免消耗 API 额度）。`health / listTools / executeTool`
>   不需要 API Key。
> - Windows 控制台中文乱码时，加 `-Dfile.encoding=UTF-8`（本仓库的示例已带）。

## 在 Java 代码中使用

### 方式一：stdio 子进程（本地调用，无需先启动服务）

```java
import com.miniagent.client.AgentProcessClient;
import java.util.Map;

try (AgentProcessClient client =
        new AgentProcessClient(".venv/Scripts/python.exe", ".", 120_000)) {

    Map<String, Object> health = client.health();

    AgentProcessClient.ChatResult r = client.chat("请审查 main.py");
    String sid = r.sessionId;                       // 保存会话 id
    AgentProcessClient.ChatResult r2 = client.chat("继续", sid);  // 多轮对话

    AgentProcessClient.ToolResult file =
            client.executeTool("read_file", Map.of("path", "main.py"));
    System.out.println(file.result);
}
```

### 方式二：HTTP（需先 `python serve.py`）

```java
import com.miniagent.client.MiniAgentClient;
import java.util.Map;

try (MiniAgentClient client = new MiniAgentClient("http://127.0.0.1:8000")) {

    MiniAgentClient.ChatResult r = client.chat("请审查 main.py");
    String sid = r.sessionId;

    MiniAgentClient.ToolResult t =
            client.executeTool("search_code", Map.of("pattern", "TODO"));
}
```

### 公共 API（两种客户端同名方法）

| 方法 | 说明 |
| --- | --- |
| `health()` | 健康检查，返回 `{status, model, tools, sessions}` |
| `listTools()` | 服务端可用工具声明（JSON Schema 列表，不含 `ask_user`） |
| `chat(message)` | 开启新会话并对话 |
| `chat(message, sessionId)` | 在既有会话上继续多轮对话 |
| `executeTool(name, arguments)` | **直接执行工具**（绕过模型），如 `read_file` / `run_shell` / `search_code` |
| `resetSession(sessionId)` | 清空会话历史 |
| `close()` | 释放资源（stdio 方式会关闭子进程） |

### 返回对象字段

- `ChatResult`：`sessionId`、`reply`（最终回复）、`promptTokens`、
  `completionTokens`、`totalTokens`、`cost`、`toolCalls`
  （本回合模型实际调用的工具记录：`name / arguments / result`）。
- `ToolResult`：`tool`、`arguments`、`ok`、`result`。

## 进阶：改成你的包结构 / 引入第三方 JSON 库

本项目为了"开箱即用"手写了一个极简 `Json` 类。如果你的工程已使用
Jackson / Gson，可以把 `Json.stringify / parse` 换成对应 API，其余代码无需改动。
