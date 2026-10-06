"""智能体 API 服务入口。

用法：
    python serve.py                          # 等价于 --mode http（默认 127.0.0.1:8000）
    python serve.py --mode http --port 9000
    python serve.py --mode stdio             # 子进程 JSON-RPC 协议（供 Java ProcessBuilder 调用）

说明：
    - HTTP 模式：Java 可用 JDK 自带的 java.net.http.HttpClient 调用；
    - stdio 模式：Java 用 ProcessBuilder 启动本进程，通过 stdin/stdout 按行交换 JSON。
    两种模式共享同一套接口（health / list_tools / execute_tool / chat / reset_session），
    详见 README.md「把智能体变成可被 Java 调用的服务」一节。
"""
import argparse
import sys

from app.server.service import AgentService


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="serve",
        description="启动 mini_agent 的对外 API 服务（HTTP 或 stdio JSON-RPC）。",
    )
    parser.add_argument(
        "--mode",
        choices=["http", "stdio"],
        default="http",
        help="http：HTTP JSON API；stdio：子进程 JSON-RPC 协议（默认 http）",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP 绑定地址（默认 127.0.0.1）")
    parser.add_argument("--port", type=int, default=8000, help="HTTP 端口（默认 8000）")
    parser.add_argument("--max-sessions", type=int, default=100, help="内存中最多保存的会话数")
    args = parser.parse_args()

    service = AgentService(max_sessions=args.max_sessions)

    if args.mode == "stdio":
        from app.server.stdio_rpc import serve_stdio

        serve_stdio(service)
        return 0

    from app.server.http_api import run_http_server

    run_http_server(host=args.host, port=args.port, service=service)
    return 0


if __name__ == "__main__":
    sys.exit(main())
