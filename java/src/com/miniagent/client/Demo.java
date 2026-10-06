package com.miniagent.client;

import java.io.File;
import java.util.List;
import java.util.Map;

/**
 * mini_agent Java 客户端演示程序。
 *
 * <p>演示两种调用方式：
 * <ol>
 *   <li><b>stdio 子进程</b>（{@link AgentProcessClient}）：Java 直接启动
 *       {@code python serve.py --mode stdio}，无需先启动服务，开箱即用；</li>
 *   <li><b>HTTP</b>（{@link MiniAgentClient}）：需要先运行
 *       {@code python serve.py}（默认 127.0.0.1:8000）。</li>
 * </ol>
 *
 * <p>编译运行（项目根目录）：
 * <pre>{@code
 * javac -encoding UTF-8 -d java/out java/src/com/miniagent/client/*.java
 * java -Dfile.encoding=UTF-8 -cp java/out com.miniagent.client.Demo [python可执行文件]
 * }</pre>
 *
 * <p>说明：health / listTools / executeTool 不需要模型与 API Key；
 * chat 会真实调用 DeepSeek 模型，需在项目 .env 中配置 DEEPSEEK_API_KEY，
 * 未配置时 chat 环节会打印错误提示但程序继续。
 */
public final class Demo {

    public static void main(String[] args) {
        // 可执行文件：默认 python；Windows 下推荐传 .venv\Scripts\python.exe
        String python = args.length > 0 ? args[0] : "python";
        // 第二个参数传 "nochat" 可跳过真实调用模型的 chat 环节（避免消耗 API 额度）
        boolean runChat = args.length < 2 || !"nochat".equalsIgnoreCase(args[1]);
        String projectDir = new File("").getAbsolutePath();

        demoProcessClient(python, projectDir, runChat);
        demoHttpClient(runChat);
    }

    /** 方式一：stdio 子进程（本地调用，无需先启动服务）。 */
    private static void demoProcessClient(String python, String projectDir, boolean runChat) {
        System.out.println("========== 方式一：stdio 子进程（AgentProcessClient） ==========");
        try (AgentProcessClient client = new AgentProcessClient(python, projectDir, 120_000)) {
            System.out.println("进程存活: " + client.isAlive());

            Map<String, Object> health = client.health();
            System.out.println("[health] status=" + health.get("status")
                    + " model=" + health.get("model") + " tools=" + health.get("tools"));

            List<Map<String, Object>> tools = client.listTools();
            System.out.println("[listTools] 共 " + tools.size() + " 个工具: "
                    + tools.stream().map(t -> (String) ((Map<?, ?>) t.get("function")).get("name")).toList());

            AgentProcessClient.ToolResult file = client.executeTool("read_file", Map.of("path", "main.py"));
            System.out.println("[executeTool(read_file)] ok=" + file.ok
                    + "\n" + abbreviate(file.result, 300));

            if (runChat) {
                System.out.println("[chat] 调用模型（需配置 DEEPSEEK_API_KEY）…");
                try {
                    AgentProcessClient.ChatResult r = client.chat("请用一句话介绍这个项目");
                    System.out.println("[chat] session=" + r.sessionId + " reply=" + r.reply);
                    AgentProcessClient.ChatResult r2 = client.chat("刚才你读了哪些工具？", r.sessionId);
                    System.out.println("[chat#2] reply=" + abbreviate(r2.reply, 200));
                } catch (Exception e) {
                    System.out.println("[chat] 失败（请确认 .env 中已配置 DEEPSEEK_API_KEY）: " + e.getMessage());
                }
            } else {
                System.out.println("[chat] 已跳过（传入 nochat 参数）");
            }
        } catch (Exception e) {
            System.out.println("方式一失败（请确认参数为可用的 python 解释器）: " + e.getMessage());
        }
        System.out.println();
    }

    /** 方式二：HTTP（需要先运行 python serve.py）。 */
    private static void demoHttpClient(boolean runChat) {
        System.out.println("========== 方式二：HTTP（MiniAgentClient，需先启动 python serve.py） ==========");
        try (MiniAgentClient client = new MiniAgentClient("http://127.0.0.1:8000")) {
            Map<String, Object> health = client.health();
            System.out.println("[health] status=" + health.get("status"));

            List<Map<String, Object>> tools = client.listTools();
            System.out.println("[listTools] 共 " + tools.size() + " 个工具");

            MiniAgentClient.ToolResult r = client.executeTool("run_shell", Map.of("command", "echo hello-from-java"));
            System.out.println("[executeTool(run_shell)] ok=" + r.ok + "\n" + abbreviate(r.result, 200));
        } catch (Exception e) {
            System.out.println("方式二失败（请先运行: python serve.py）: " + e.getMessage());
        }
    }

    private static String abbreviate(String s, int max) {
        if (s == null) {
            return "";
        }
        return s.length() <= max ? s : s.substring(0, max) + "\n…（已截断）";
    }

    private Demo() {
    }
}
