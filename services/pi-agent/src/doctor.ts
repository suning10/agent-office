/**
 * pi 侧自检：验证 pi 框架 + DeepSeek 提供方能否通过 pi Agent loop 正常对话。
 *
 * 说明：
 * - DeepSeek 是唯一对话模型（关键路径，决定退出码）。
 * - Embedding / bge 重排在 Python 后端本地运行，见 backend/scripts/doctor.py。
 *
 * 用法：npm run doctor
 */
import { loadConfig } from "./config.js";
import { buildModels, getMainModel } from "./providers.js";
import { buildTools } from "./tools.js";
import { runAgent, type AgentRuntime } from "./agents.js";
import type { Model } from "@earendil-works/pi-ai";

interface DoctorResult {
  name: string;
  ok: boolean;
  critical: boolean;
  sample?: string;
  error?: string;
}

async function checkModel(
  name: string,
  model: Model<"openai-completions">,
  runtime: AgentRuntime,
  critical: boolean,
): Promise<DoctorResult> {
  try {
    const out = await runAgent({ ...runtime, model }, "你是助手，请只回复两个字：OK", "你好");
    return { name, ok: out.length > 0, critical, sample: out.slice(0, 80) };
  } catch (err) {
    return { name, ok: false, critical, error: String(err) };
  }
}

async function main(): Promise<void> {
  const config = loadConfig();
  const models = buildModels(config);
  const tools = buildTools(config);
  const runtime: AgentRuntime = {
    model: getMainModel(models, config),
    streamFn: models.streamSimple.bind(models),
    tools,
  };

  const results: DoctorResult[] = [];
  results.push(await checkModel("pi + DeepSeek Agent", getMainModel(models, config), runtime, true));

  console.log("=".repeat(60));
  console.log("pi-agent 自检");
  console.log("=".repeat(60));
  for (const r of results) {
    const mark = r.ok ? "PASS" : r.critical ? "FAIL" : "WARN";
    console.log(`[${mark}] ${r.name}`);
    if (r.ok) console.log(`       sample: ${r.sample}`);
    else console.log(`       ${r.error ? "error : " + r.error : "未获得输出"}`);
  }
  console.log("=".repeat(60));

  const criticalOk = results.filter((r) => r.critical).every((r) => r.ok);
  process.exit(criticalOk ? 0 : 1);
}

main();
