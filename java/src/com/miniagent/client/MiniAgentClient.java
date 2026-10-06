package com.miniagent.client;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * mini_agent HTTP JSON API 客户端（基于 JDK 11+ 的 {@link java.net.http.HttpClient}，
 * 零第三方依赖）。
 *
 * <p>典型用法：
 * <pre>{@code
 * try (MiniAgentClient c = new MiniAgentClient("http://127.0.0.1:8000")) {
 *     Map<String,Object> health = c.health();
 *     MiniAgentClient.ChatResult r = c.chat("请审查 main.py");
 *     String sid = r.sessionId;                       // 保存会话 id
 *     MiniAgentClient.ChatResult r2 = c.chat("继续", sid);  // 多轮对话
 *     Map<String,Object> file = c.executeTool("read_file", Map.of("path", "main.py"));
 * }
 * }</pre>
 */
public class MiniAgentClient implements AutoCloseable {

    private final HttpClient http;
    private final String base;

    /** 一次对话的结果。 */
    public static final class ChatResult {
        public final String sessionId;
        public final String reply;
        public final long promptTokens;
        public final long completionTokens;
        public final long totalTokens;
        public final double cost;
        /** 本回合模型实际调用的工具记录：{name, arguments, result} 列表。 */
        public final List<Map<String, Object>> toolCalls;

        ChatResult(Map<String, Object> data) {
            this.sessionId = str(data.get("session_id"));
            this.reply = str(data.get("reply"));
            this.promptTokens = num(data.get("prompt_tokens"));
            this.completionTokens = num(data.get("completion_tokens"));
            this.totalTokens = num(data.get("total_tokens"));
            this.cost = numDouble(data.get("cost"));
            this.toolCalls = mapList(data.get("tool_calls"));
        }

        @Override
        public String toString() {
            return "ChatResult{sessionId='" + sessionId + "', reply='" + truncate(reply, 80)
                    + "', totalTokens=" + totalTokens + ", cost=" + cost + "}";
        }
    }

    /** 直接执行工具的结果。 */
    public static final class ToolResult {
        public final String tool;
        public final Map<String, Object> arguments;
        public final boolean ok;
        public final String result;

        ToolResult(Map<String, Object> data) {
            this.tool = str(data.get("tool"));
            this.ok = Boolean.TRUE.equals(data.get("ok"));
            this.result = str(data.get("result"));
            Object args = data.get("arguments");
            this.arguments = args instanceof Map ? strMap((Map<?, ?>) args) : Map.of();
        }

        @Override
        public String toString() {
            return "ToolResult{tool='" + tool + "', ok=" + ok + ", result='" + truncate(result, 80) + "'}";
        }
    }

    public MiniAgentClient(String baseUrl) {
        this.base = baseUrl.endsWith("/") ? baseUrl.substring(0, baseUrl.length() - 1) : baseUrl;
        this.http = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(10))
                .build();
    }

    /** GET /health */
    public Map<String, Object> health() throws IOException, InterruptedException {
        return getMap("/health");
    }

    /** GET /v1/tools —— 服务端可用工具声明（不含 ask_user）。 */
    public List<Map<String, Object>> listTools() throws IOException, InterruptedException {
        Map<String, Object> resp = getMap("/v1/tools");
        return mapList(resp.get("tools"));
    }

    /** POST /v1/chat —— 开启新会话。 */
    public ChatResult chat(String message) throws IOException, InterruptedException {
        return chat(message, null, null);
    }

    /** POST /v1/chat —— 在既有会话上继续多轮对话。 */
    public ChatResult chat(String message, String sessionId) throws IOException, InterruptedException {
        return chat(message, sessionId, null);
    }

    /** POST /v1/chat —— 可显式指定最大工具轮次。 */
    public ChatResult chat(String message, String sessionId, Integer maxRounds)
            throws IOException, InterruptedException {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("message", message);
        if (sessionId != null) {
            body.put("session_id", sessionId);
        }
        if (maxRounds != null) {
            body.put("max_rounds", maxRounds);
        }
        Map<String, Object> resp = postMap("/v1/chat", body);
        if (resp.containsKey("error")) {
            throw new IOException("服务端返回错误: " + resp.get("error"));
        }
        return new ChatResult(resp);
    }

    /** POST /v1/tools/&lt;name&gt;/execute —— 直接执行工具，绕过模型。 */
    public ToolResult executeTool(String name, Map<String, Object> arguments)
            throws IOException, InterruptedException {
        Map<String, Object> resp = postMap("/v1/tools/" + name + "/execute", arguments);
        return new ToolResult(resp);
    }

    /** POST /v1/sessions/&lt;id&gt;/reset —— 重置会话历史。 */
    public boolean resetSession(String sessionId) throws IOException, InterruptedException {
        Map<String, Object> resp = postMap("/v1/sessions/" + sessionId + "/reset", Map.of());
        return Boolean.TRUE.equals(resp.get("ok"));
    }

    // ------------------------------------------------------------------
    // 内部 HTTP 工具
    // ------------------------------------------------------------------
    private Map<String, Object> getMap(String path) throws IOException, InterruptedException {
        return send("GET", path, null);
    }

    private Map<String, Object> postMap(String path, Object body) throws IOException, InterruptedException {
        return send("POST", path, body);
    }

    private Map<String, Object> send(String method, String path, Object body)
            throws IOException, InterruptedException {
        HttpRequest.Builder builder = HttpRequest.newBuilder()
                .uri(URI.create(base + path))
                .timeout(Duration.ofMinutes(5))
                .header("Content-Type", "application/json; charset=utf-8");
        if ("GET".equals(method)) {
            builder.GET();
        } else {
            builder.POST(HttpRequest.BodyPublishers.ofString(Json.stringify(body), java.nio.charset.StandardCharsets.UTF_8));
        }
        HttpResponse<String> resp = http.send(builder.build(), HttpResponse.BodyHandlers.ofString(java.nio.charset.StandardCharsets.UTF_8));
        Map<String, Object> data = Json.parseObject(resp.body());
        if (resp.statusCode() >= 400) {
            Object err = data.get("error");
            if (err == null) {
                err = data.get("result") != null ? data.get("result") : ("HTTP " + resp.statusCode());
            }
            throw new IOException("HTTP " + resp.statusCode() + ": " + err);
        }
        return data;
    }

    // ------------------------------------------------------------------
    // 类型转换辅助（包级可见，供 AgentProcessClient 复用）
    // ------------------------------------------------------------------
    static String str(Object v) {
        return v == null ? "" : String.valueOf(v);
    }

    static long num(Object v) {
        return v instanceof Number ? ((Number) v).longValue() : 0L;
    }

    static double numDouble(Object v) {
        return v instanceof Number ? ((Number) v).doubleValue() : 0.0;
    }

    static Map<String, Object> strMap(Map<?, ?> m) {
        Map<String, Object> out = new LinkedHashMap<>();
        for (Map.Entry<?, ?> e : m.entrySet()) {
            out.put(String.valueOf(e.getKey()), e.getValue());
        }
        return out;
    }

    static List<Map<String, Object>> mapList(Object v) {
        List<Map<String, Object>> out = new ArrayList<>();
        if (v instanceof Iterable) {
            for (Object item : (Iterable<?>) v) {
                if (item instanceof Map) {
                    out.add(strMap((Map<?, ?>) item));
                }
            }
        }
        return out;
    }

    static String truncate(String s, int max) {
        return s.length() <= max ? s : s.substring(0, max) + "…";
    }

    @Override
    public void close() {
        // HttpClient 无需显式关闭；为满足 AutoCloseable 契约提供空实现
    }
}
