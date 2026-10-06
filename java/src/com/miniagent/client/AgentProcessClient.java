package com.miniagent.client;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.File;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * mini_agent stdio JSON-RPC 客户端：Java 直接启动 Python 子进程
 * （{@code python serve.py --mode stdio}），通过标准输入输出按行交换 JSON。
 *
 * <p>与 HTTP 方式相比，它不需要端口、不需要先启动服务，进程由 Java 管理，
 * 使用方式更接近"本地调用"（类似把智能体当做一个可交互的子程序）。
 *
 * <p>典型用法：
 * <pre>{@code
 * try (AgentProcessClient c = new AgentProcessClient("python", ".", 10_000)) {
 *     Map<String,Object> health = c.health();
 *     AgentProcessClient.ChatResult r = c.chat("请审查 main.py");
 *     c.executeTool("read_file", Map.of("path", "main.py"));
 * }
 * }</pre>
 *
 * <p>注意：同一时刻仅允许一个调用在途（服务端顺序处理请求）；所有方法
 * 内部已同步。stderr 由后台线程消费丢弃，避免管道缓冲阻塞 Python 进程。
 */
public class AgentProcessClient implements AutoCloseable {

    private final Process process;
    private final BufferedReader reader;
    private final BufferedWriter writer;
    private final Object lock = new Object();
    private long nextId = 1;

    /** 对话结果（字段含义与 HTTP 客户端一致）。 */
    public static final class ChatResult {
        public final String sessionId;
        public final String reply;
        public final long promptTokens;
        public final long completionTokens;
        public final long totalTokens;
        public final double cost;
        public final List<Map<String, Object>> toolCalls;

        ChatResult(Map<String, Object> data) {
            this.sessionId = MiniAgentClient.str(data.get("session_id"));
            this.reply = MiniAgentClient.str(data.get("reply"));
            this.promptTokens = MiniAgentClient.num(data.get("prompt_tokens"));
            this.completionTokens = MiniAgentClient.num(data.get("completion_tokens"));
            this.totalTokens = MiniAgentClient.num(data.get("total_tokens"));
            this.cost = MiniAgentClient.numDouble(data.get("cost"));
            this.toolCalls = MiniAgentClient.mapList(data.get("tool_calls"));
        }

        @Override
        public String toString() {
            return "ChatResult{sessionId='" + sessionId + "', reply='"
                    + MiniAgentClient.truncate(reply, 80) + "', totalTokens=" + totalTokens + "}";
        }
    }

    /** 工具执行结果。 */
    public static final class ToolResult {
        public final String tool;
        public final boolean ok;
        public final String result;

        ToolResult(Map<String, Object> data) {
            this.tool = MiniAgentClient.str(data.get("tool"));
            this.ok = Boolean.TRUE.equals(data.get("ok"));
            this.result = MiniAgentClient.str(data.get("result"));
        }

        @Override
        public String toString() {
            return "ToolResult{tool='" + tool + "', ok=" + ok + "}";
        }
    }

    /**
     * 启动子进程。
     *
     * @param pythonExecutable 解释器路径，例如 "python" 或 ".venv/Scripts/python.exe"
     * @param projectDir       项目根目录（serve.py 所在目录），用于设置工作目录
     * @param timeoutMs        单次调用的超时（毫秒）；0 表示不超时
     */
    public AgentProcessClient(String pythonExecutable, String projectDir, long timeoutMs)
            throws IOException {
        ProcessBuilder pb = new ProcessBuilder(pythonExecutable, "serve.py", "--mode", "stdio");
        pb.directory(new File(projectDir));
        // 重要：不能合并 stderr 到 stdout，否则会破坏 JSON 行协议
        pb.redirectErrorStream(false);
        process = pb.start();
        reader = new BufferedReader(new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8));
        writer = new BufferedWriter(new OutputStreamWriter(process.getOutputStream(), StandardCharsets.UTF_8));

        // 后台消费 stderr（丢弃），防止缓冲满后阻塞 Python 进程
        Thread drain = new Thread(() -> {
            try (BufferedReader err = new BufferedReader(
                    new InputStreamReader(process.getErrorStream(), StandardCharsets.UTF_8))) {
                while (err.readLine() != null) {
                    // discard
                }
            } catch (IOException ignored) {
                // 进程退出后正常结束
            }
        }, "miniagent-stderr-drain");
        drain.setDaemon(true);
        drain.start();
    }

    // ------------------------------------------------------------------
    // 对外方法（与 HTTP 客户端同名）
    // ------------------------------------------------------------------
    public Map<String, Object> health() throws IOException {
        return (Map<String, Object>) call("health", Map.of());
    }

    @SuppressWarnings("unchecked")
    public List<Map<String, Object>> listTools() throws IOException {
        Map<String, Object> result = (Map<String, Object>) call("list_tools", Map.of());
        Object tools = result.get("tools");
        List<Map<String, Object>> out = new ArrayList<>();
        if (tools instanceof Iterable) {
            for (Object item : (Iterable<?>) tools) {
                if (item instanceof Map) {
                    out.add(MiniAgentClient.strMap((Map<?, ?>) item));
                }
            }
        }
        return out;
    }

    public ChatResult chat(String message) throws IOException {
        return chat(message, null, null);
    }

    public ChatResult chat(String message, String sessionId) throws IOException {
        return chat(message, sessionId, null);
    }

    public ChatResult chat(String message, String sessionId, Integer maxRounds) throws IOException {
        Map<String, Object> params = new LinkedHashMap<>();
        params.put("message", message);
        if (sessionId != null) {
            params.put("session_id", sessionId);
        }
        if (maxRounds != null) {
            params.put("max_rounds", maxRounds);
        }
        Object result = call("chat", params);
        return new ChatResult((Map<String, Object>) result);
    }

    public ToolResult executeTool(String name, Map<String, Object> arguments) throws IOException {
        Map<String, Object> params = new LinkedHashMap<>();
        params.put("name", name);
        params.put("arguments", arguments == null ? Map.of() : arguments);
        Object result = call("execute_tool", params);
        return new ToolResult((Map<String, Object>) result);
    }

    public boolean resetSession(String sessionId) throws IOException {
        Object result = call("reset_session", Map.of("session_id", sessionId));
        return Boolean.TRUE.equals(((Map<String, Object>) result).get("ok"));
    }

    // ------------------------------------------------------------------
    // 协议核心：发一行请求，读一行响应
    // ------------------------------------------------------------------
    private Object call(String method, Map<String, Object> params) throws IOException {
        synchronized (lock) {
            Map<String, Object> req = new LinkedHashMap<>();
            req.put("id", nextId++);
            req.put("method", method);
            req.put("params", params);
            writer.write(Json.stringify(req));
            writer.newLine();
            writer.flush();

            String line = reader.readLine();
            if (line == null) {
                throw new IOException("子进程已退出（exit=" + process.exitValue() + "）");
            }
            Map<String, Object> resp = Json.parseObject(line);
            if (resp.containsKey("error")) {
                Map<?, ?> err = (Map<?, ?>) resp.get("error");
                throw new IOException("JSON-RPC 错误 " + err.get("code") + ": " + err.get("message"));
            }
            return resp.get("result");
        }
    }

    /** 子进程是否仍在运行。 */
    public boolean isAlive() {
        return process.isAlive();
    }

    @Override
    public void close() {
        synchronized (lock) {
            try {
                process.destroy();
            } finally {
                try {
                    if (!process.waitFor(3, java.util.concurrent.TimeUnit.SECONDS)) {
                        process.destroyForcibly();
                    }
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    process.destroyForcibly();
                }
            }
        }
    }
}
