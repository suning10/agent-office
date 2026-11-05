# Agent orchestration overview

`Orchestrator.answer()` in `harness/orchestrator.py` coordinates the agents through a **fixed DAG written as plain Python**: one `async` method calls the agents in order, with one bounded retry loop. There is no LangGraph, LangChain or AutoGen, and no LLM decides which agent runs next. The control flow is deterministic, and the LLM is used only *inside* each step.

## Entry points

| Caller | Route | Notes |
|---|---|---|
| User chat | `POST /api/v1/chat` → `orchestrator.answer()` | Checks the session owner first. |
| User chat, SSE | `POST /api/v1/chat/stream` → `answer_stream()` | Runs the full `answer()` and then sends the finished text in 16-character slices. It is not real token streaming, and it does not pass `dept_ids`. |
| Department pod | `POST /api/v1/internal/dept/answer` | A department agent pod (`DEPT_ID` set) runs the **same orchestrator**, restricted to its own department. |

Each call is one Langfuse trace (`orchestrator.answer`, `as_type="agent"`). `session_id` and `user_id` are passed down to every child agent and LLM call.

## The agents

All of them are built in `deps.py` and passed into the `Orchestrator` constructor.

| Agent | File | Input → output | Primary path | Fallback |
|---|---|---|---|---|
| DeptRouter | `agents/dept_router.py` | query → `{dept_ids, matched_by, confidence, reasons}` | Keyword table, then an LLM JSON call | All departments |
| IntentAgent | `agents/intent_agent.py` | query + memory → `Intent` (type, depts, user_role, entities, needs_cross_dept) | pi runtime `intent`, then the local LLM | Keyword rules |
| QueryRewriter | `agents/query_rewriter.py` | query + glossary + memory → 1–3 queries | pi runtime `rewrite`, then the local LLM | Glossary synonym expansion |
| RetrievalAgent | `agents/retrieval_agent.py` | queries × depts → top-k chunks | Hybrid BM25 + vector + rerank (see `pipeline/rag.md`) | n/a (no LLM) |
| AnswerAgent | `agents/answer_agent.py` | query + chunks + rules + memory → `Answer` with `[来源N]` citations | pi runtime `answer` (`allowed_tools=[]`), then the local LLM | Stitches together excerpts of the original chunks |
| VerifierAgent | `agents/verifier_agent.py` | query + answer + chunks → `VerificationResult(passed, score, issues)` | pi runtime `verify`, then the local LLM | Heuristic: has citations, not empty |
| FeedbackAgent | `agents/feedback_agent.py` | writes a `feedback` record for the Loop engine | No LLM | n/a |

Shared types live in `harness/base.py`: `Intent`, `Answer`, `Citation` and `VerificationResult`.

### Three-level fallback for each agent

Each LLM-backed agent tries up to three implementations in order:

```
pi runtime (TS service, POST /v1/agent/run)  →  local LLMClient (DeepSeek / Ollama)  →  rules/heuristics
```

- `PiAgentRuntimeClient` (`integrations/pi_runtime.py`) returns `None` in two cases: when it is disabled (it needs `PI_AGENT_ENABLED`, `PI_AGENT_URL` and `INTERNAL_API_TOKEN`), or when the call fails. The agent then quietly moves to the next level.
- Python passes an explicit `allowed_tools` whitelist, so pi cannot widen its own tool permissions or skip the fact retrieval step.
- Timeouts per pi call come from `PI_RUNTIME_TIMEOUT_*` (intent 8s, rewrite 10s, answer 45s, verify 20s).

The result is that the system keeps answering even when no model is reachable; `tests/test_e2e.py` relies on this. The cost is that quality can drop without anyone noticing.

## Flow of `_answer()`

```
           ┌──────────── control plane: Python ────────────┐
query ─► 0 dept scope ─► memory ─► hooks ─► 3 Intent ─► 4 hook expansion + rules + full memory
                                                     │
                     dept agents enabled? ──yes──► fan out to dept pods (parallel) ─► merge ─► finalize
                                                     │no
            5 Rewrite + Skill plan ─► 6 Retrieve (+ org-memory evidence) ─► 7 Answer ─► 8 Verify ⟲ ×2 ─► 9 finalize
```

### Step by step

**0. Department scope**
- On a department pod (`settings.dept_id` set), a request for any other department raises `PermissionError`, and the scope is forced to `[dept_id]`.
- Otherwise, if the caller passed no `dept_ids`, `DeptRouter.route()` picks them. The routing result is returned to the frontend as `route`, so it can show which department was chosen.

**Memory, first pass**
- Appends the user message to working memory (Redis) and episodic memory (`conversation_events`).
- If the previous turn was an assistant answer, records an implicit `follow_up` signal. Asking again in the same session counts as weak negative feedback.
- Builds `initial_memory` with `MemoryContextBuilder.build(..., include_organization=False)`.

**1. Hooks:** loads active hooks with `hook_engine.active_hooks()`.

**3. Intent:** `IntentAgent.infer()` receives the external and initial memory as profile context. The intent is saved to working memory.
(Step 2 is missing from the numbering. The module docstring mentions an FAQ-cache step, but the orchestrator does not implement one.)

**4. Expanding the scope**
- `resolved_depts` is the departments from step 0 if there were any, otherwise `intent.depts`.
- `hook_engine.evaluate()` and `apply()` can add departments for cross-department queries. For example, a `cross_dept_retrieval` hook adds 财务处 when the query mentions 缴费 or 退费.
- Loads `rule_engine.active_rules(resolved_depts)`. These become the hard constraints in the answer prompt.
- Builds the full memory context (`include_organization=True`, role-aware) into `memory_prompt`.

**Branch: fan-out to department agents** (only when `DEPT_AGENTS_ENABLED=true` and this instance is not itself a department pod)
- `DepartmentAgentClient.answer_many()` calls every department pod at once with `asyncio.gather`. Each pod gets `{base}/api/v1/internal/dept/answer`, with a `DEPT_AGENT_TIMEOUT` of 6s and a 2s connect timeout.
- Departments that fail are answered locally from shared retrieval instead, and listed as `degraded`.
- `_merge_department_answers()` concatenates one `【部门】` section per department, merges the citations, and averages the confidence. `verification.partial` and `failed_departments` record what went wrong.
- Skips steps 5–8 and goes straight to finalize. The merged answer is **not** verified again, because each pod has already run its own verifier.

**5. Rewrite and skills**
- `QueryRewriter.rewrite()` produces the retrieval queries.
- `SkillExecutor.matching()` and `prepare()` apply active skills. Each skill is assigned to a treatment or control group by a hash of user, session, skill and version, according to `gray_percent`. Every assignment is logged to `strategy_executions` for A/B evaluation.
- Treatment skills can add queries, raise `top_k`, or add instructions (output template, school-calendar rule, rubric rules).

**6. Retrieve**
- `RetrievalAgent.retrieve(skill_plan.queries, resolved_depts, top_k)`.
- Source chunks from organization memory (`memory_context.evidence_chunks`) are placed *first*, then the retrieved chunks, de-duplicated by chunk id and cut to `top_k`.
- Memory can only point back to official facts. The memory text itself is never cited.

**7. Answer:** `AnswerAgent.generate()` receives the chunks, rules, intent, the skill instructions as `extra_instructions`, and `memory_prompt`. The prompt marks memory as "context and style only, not a fact or citation source". `_enrich_citations()` fills in document titles and department ids.

**8. Verify loop** (`MAX_VERIFY_RETRY = 2`)
- `VerifierAgent.verify()` checks citation support, contradictions, omissions and citation format.
- If it fails, the answer is generated again with `"上次回答存在以下问题，请修正：<issues>"`.
- Afterwards, skill trigger and success metrics are updated (`_record_skill_usage`).

**9. Finalize** (`_finalize()`)
- Appends the assistant message to working memory.
- `FeedbackAgent.collect()` records an automatic `verifier_pass` or `verifier_fail` signal.
- `loop_engine.record_trace()` writes a full trace for Loop replay. The trace holds the query, intent, chunks, answer, citations, verification, latency and `langfuse_trace_id`; the Langfuse id lets user feedback be scored back onto the trace.
- Appends an episodic `assistant_message` event and a rolling summary built without an LLM (the last 4 messages, 240 characters each).
- Updates user memory (`record_query`) and department hot-query counters.
- Updates the Prometheus metrics `QUERY_TOTAL` and `QUERY_LATENCY`.
- Afterwards, `skill_executor.record_outcome()` and `memory_context_builder.record_usage()` link the skill executions and memory hits to the `trace_id`.

The response contains `session_id`, `answer`, `citations`, `dept_ids`, `confidence`, `intent_type`, `verification`, `retrieved_count` and `route`.

## How orchestration links to the Loop (self-improvement)

The orchestrator *uses* artifacts that the Loop engine (`app/loop/`) produces, and *feeds* signals back to it:

| Artifact | Used at | Effect |
|---|---|---|
| Hooks | Step 4 | Widen the department scope |
| Rules | Steps 4 and 7 | Hard constraints in the answer prompt |
| Skills | Steps 5 and 7 | Extra queries, top-k, and output instructions; A/B grey release |
| Feedback and traces | Step 9 | Input for mining new skills, hooks and rules, and for rollback decisions |

## Design properties

- **Deterministic control flow** makes the system easy to reason about, test and trace. The Langfuse span tree matches the code.
- **Every LLM step has a structured contract** (JSON in, typed dataclass out) and its own fallback.
- **Fact and memory separation:** only chunks from the fact plane can be cited, while memory only steers what gets retrieved.
- **The same orchestrator runs in every deployment shape**: a single monolith, a coordinator that fans out to department pods, or a department pod itself.

## Known issues and limitations

- **A twice-failed answer is recorded as passed.**
  - What happens: in the verify loop, if both checks fail, the loop ends right after the second regeneration. `AnswerAgent.generate()` returns a new `Answer` whose `verification` is `{}`, and every later `verification.get("passed", True)` reads that as passed.
  - Consequences: the trace, the auto-feedback signal and the skill success rate are all recorded as **passed**, and the final answer is never checked.
  - Fix: verify once more after the last rewrite, or carry the last verdict over.
- **Everything runs one after another.** Intent and rewrite could run in parallel, and so could the queries × departments retrieval loop. Today each step waits for the previous one, so latency is the sum of the step times. Only the department fan-out runs in parallel.
- **Routing is done twice.**
  - `DeptRouter` can make an LLM call to choose departments, and then `IntentAgent` makes a second LLM call that also returns `depts`.
  - When the router succeeded, the intent's departments are ignored.
- **The fake SSE stream** only arrives after the whole pipeline has finished, and it ignores `dept_ids`.
- **Unused settings and code:**
  - `settings.timeout_intent/retrieval/answer/verify` are never read; only the `pi_runtime_timeout_*` values are.
  - Some orchestrator code is never called: `pi_client`, `_answer_from_pi`, `_match_active_skills` and `_skill_hint_text`.
- **Hook expansion is hardcoded.** `HookEngine.apply()` maps keywords to departments with a static table, whatever the hook's own configuration says.
- **No overall deadline.** Each pi call has its own timeout, but a single request has no total time budget. In the worst case it waits for intent, rewrite, answer and two rounds of verify plus regenerate, one after another.
