/**
 * 集中配置：从环境变量读取（Docker 由 compose 注入，本地可配 .env）。
 * DeepSeek 为唯一对话模型；Embedding / bge 重排由 Python 后端本地运行。
 */

function str(name: string, fallback: string): string {
  return process.env[name] ?? fallback;
}

function num(name: string, fallback: number): number {
  const v = process.env[name];
  if (v === undefined || v === "") return fallback;
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

export interface Config {
  port: number;
  host: string;
  backendUrl: string;
  /** 调用后端 /internal/* 所需的共享令牌（与后端 INTERNAL_API_TOKEN 一致） */
  internalApiToken: string;

  deepseekApiKey: string;
  deepseekBaseUrl: string;
  deepseekModel: string;

  loopEnabled: boolean;
  loopPhase: "human_in_loop" | "human_on_loop" | "human_out_of_loop";
  hookHighConfidence: number;
}

export function loadConfig(): Config {
  return {
    port: num("PORT", 8100),
    host: str("HOST", "0.0.0.0"),
    backendUrl: str("BACKEND_URL", "http://localhost:8000"),
    internalApiToken: str("INTERNAL_API_TOKEN", ""),

    deepseekApiKey: str("DEEPSEEK_API_KEY", ""),
    deepseekBaseUrl: str("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    deepseekModel: str("DEEPSEEK_MODEL", "deepseek-v4-flash"),

    loopEnabled: str("LOOP_ENABLED", "true") === "true",
    loopPhase: (str("LOOP_PHASE", "human_on_loop") as Config["loopPhase"]),
    hookHighConfidence: num("HOOK_HIGH_CONFIDENCE", 0.9),
  };
}
