"""API 服务层：把命令行智能体暴露为可被外部程序（如 Java）调用的服务。

包含两个对外协议，共享同一个 AgentService 内核：

- http_api.py    —— HTTP JSON API（Java 用 java.net.http.HttpClient 等调用）
- stdio_rpc.py   —— stdin/stdout 上的 JSON-RPC 子进程协议（Java 用 ProcessBuilder 启动）

AgentService（service.py）封装会话管理、对话、直接执行工具等能力，
不依赖任何具体传输层，可被测试直接驱动。
"""
