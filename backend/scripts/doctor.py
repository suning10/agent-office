"""环境自检脚本（doctor）：验证 DeepSeek 对话模型与本地 Embedding / 重排模型能否成功调用。

用法：
    cd backend
    python -m scripts.doctor          # 使用 .env / 环境变量中的密钥
    python -m scripts.doctor --json   # 输出 JSON 结果（供 CI / 前端展示）

检查项：
    1. 对话模型：DeepSeek（默认 deepseek-v4-flash）或 LLM_PROVIDER=ollama 时的本地 Ollama
    2. Embedding 模型：本地 sentence-transformers（默认 BAAI/bge-m3）或 Ollama /embeddings
    3. 本地重排模型（默认 BAAI/bge-reranker-v2-m3，CrossEncoder）

退出码：全部通过返回 0，任一失败返回 1。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

# 默认配置（与 .env 一致；经 doctor 实测校验过的可用模型名）
DEFAULT_DEEPSEEK_BASE = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
DEFAULT_EMBED_MODEL = "BAAI/bge-m3"                  # 本地 Embedding（1024 维）
DEFAULT_RERANK_MODEL = "BAAI/bge-reranker-v2-m3"     # 本地 bge 重排模型
DEFAULT_OLLAMA_BASE = "http://localhost:11434/v1"
DEFAULT_OLLAMA_MODEL = "qwen3.5:0.8b"


def _load_env() -> None:
    """加载 program/.env 或 backend/.env（不覆盖已存在的环境变量）。"""
    candidates = [
        Path.cwd() / ".env",
        Path.cwd().parent / ".env",          # 从 backend/ 运行时读 program/.env
        Path(__file__).resolve().parents[2] / ".env",
    ]
    for path in candidates:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)
        return


def _env(name: str, default: str) -> str:
    """读取环境变量并去掉 .env 行内注释（如 `RERANKER_ENABLED=true   # ...`）。"""
    return os.environ.get(name, default).split("#", 1)[0].strip()


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


async def check_chat(
    base_url: str, api_key: str, model: str, name: str, timeout: float = 30.0, extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    """检查对话模型 /chat/completions。"""
    started = time.perf_counter()
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "请用一句话介绍你自己。"}],
        "temperature": 0.1,
        "max_tokens": 64,
        "stream": False,
        **(extra or {}),
    }
    result = {"name": name, "kind": "chat", "model": model, "url": url, "ok": False}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=_headers(api_key), json=payload)
        latency = round((time.perf_counter() - started) * 1000, 1)
        result["latency_ms"] = latency
        result["status"] = resp.status_code
        if resp.status_code == 200:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            result["ok"] = bool(content)
            result["sample"] = content[:120]
            if not content:
                result["error"] = "content 为空（思考模型可能把 max_tokens 耗尽在 reasoning 上）"
        else:
            result["error"] = resp.text[:500]
    except httpx.HTTPError as exc:
        result["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


async def check_ollama_embedding(base_url: str, model: str, name: str, timeout: float = 30.0) -> dict[str, Any]:
    """检查 Ollama /embeddings（OpenAI 兼容）。"""
    started = time.perf_counter()
    url = base_url.rstrip("/") + "/embeddings"
    result: dict[str, Any] = {"name": name, "kind": "embedding", "model": model, "url": url, "ok": False}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json={"model": model, "input": ["跨部门文档问答助手"]})
        result["status"] = resp.status_code
        if resp.status_code == 200:
            vec = resp.json()["data"][0]["embedding"]
            result["ok"] = True
            result["dim"] = len(vec)
            result["sample"] = f"dim={len(vec)}, head={vec[:3]}"
        else:
            result["error"] = resp.text[:500]
    except httpx.HTTPError as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return result


def check_embedding(model: str, name: str) -> dict[str, Any]:
    """检查本地 Embedding 模型（sentence-transformers，首次运行会下载模型）。"""
    started = time.perf_counter()
    result: dict[str, Any] = {"name": name, "kind": "embedding", "model": model, "url": "local", "ok": False}
    try:
        from sentence_transformers import SentenceTransformer

        vec = SentenceTransformer(model).encode(["跨部门文档问答助手"], normalize_embeddings=True)[0]
        result["ok"] = True
        result["dim"] = len(vec)
        result["sample"] = f"dim={len(vec)}, head={[round(float(x), 4) for x in vec[:3]]}"
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return result


def check_rerank(model: str, name: str) -> dict[str, Any]:
    """检查本地 bge 重排模型（CrossEncoder）。"""
    started = time.perf_counter()
    result: dict[str, Any] = {"name": name, "kind": "rerank", "model": model, "url": "local", "ok": False}
    try:
        from sentence_transformers import CrossEncoder

        scores = CrossEncoder(model).predict([("选课时间", "选课在第16至18周进行"), ("选课时间", "学费在开学前缴纳")])
        result["ok"] = True
        result["sample"] = f"top scores={[round(float(s), 4) for s in scores[:3]]}"
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return result


async def run_all() -> list[dict[str, Any]]:
    _load_env()
    deepseek_base = os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_DEEPSEEK_BASE)
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")
    deepseek_model = os.environ.get("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL)
    embed_model = os.environ.get("EMBEDDING_MODEL", DEFAULT_EMBED_MODEL)
    rerank_model = os.environ.get("RERANKER_MODEL", DEFAULT_RERANK_MODEL)

    ollama_base = _env("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE)
    embedding_provider = _env("EMBEDDING_PROVIDER", "local").lower()

    results = []
    if _env("LLM_PROVIDER", "deepseek").lower() == "ollama":
        effort = _env("OLLAMA_REASONING_EFFORT", "none")
        results.append(await check_chat(
            ollama_base, "ollama", _env("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL), "Ollama 对话", timeout=120.0,
            extra={"reasoning_effort": effort} if effort else None,
        ))
    else:
        results.append(await check_chat(deepseek_base, deepseek_key, deepseek_model, "DeepSeek 对话"))
    if embedding_provider == "local":
        results.append(check_embedding(embed_model, "本地 Embedding"))
    elif embedding_provider == "ollama":
        results.append(await check_ollama_embedding(ollama_base, embed_model, "Ollama Embedding"))
    if _env("RERANKER_ENABLED", "true").lower() == "true":
        results.append(check_rerank(rerank_model, "本地 bge 重排"))
    return results


def _print_report(results: list[dict[str, Any]]) -> None:
    print("=" * 66)
    print("文枢 · 模型连通性自检（doctor）")
    print("=" * 66)
    for r in results:
        mark = "PASS" if r["ok"] else "FAIL"
        print(f"[{mark}] {r['name']:24s} model={r['model']:20s} "
              f"status={r.get('status', '-')} latency={r.get('latency_ms', '-')}ms")
        if r["ok"]:
            print(f"       sample: {r.get('sample', '')}")
        else:
            print(f"       error : {r.get('error', '')[:200]}")
    all_ok = all(r["ok"] for r in results)
    print("-" * 66)
    print("结论：", "全部通过 ✅" if all_ok else "存在失败项 ❌")
    print("=" * 66)


async def main() -> int:
    parser = argparse.ArgumentParser(description="文枢模型连通性自检")
    parser.add_argument("--json", action="store_true", help="输出 JSON 结果")
    args = parser.parse_args()

    results = await run_all()
    if args.json:
        print(json.dumps({"results": results, "all_ok": all(r["ok"] for r in results)}, ensure_ascii=False, indent=2))
    else:
        _print_report(results)
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
