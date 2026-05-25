import asyncio
import json
import http.client
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import logging
import debug as _debug

SELFCHAT_TOOLS = [
    {
        "name": "selfchat_create",
        "description": (
            "Create a new self-chat session with yourself (the same model). "
            "Returns a session_id to use in subsequent selfchat_send calls. "
            "Useful for inner monologue, chain-of-thought reasoning, brainstorming, self-critique, or running a second instance of yourself as a subagent. "
            "To give the agent access to real MCP tools, pass tool names in the 'tools' list parameter — "
            "the agent will be able to call them using TOOL_CALL: syntax and receive real results."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "system_prompt": {
                    "type": "string",
                    "description": "System prompt for the inner model instance."
                },
                "model": {
                    "type": "string",
                    "description": "Model identifier to use. Omit to use the currently loaded model."
                },
                "lmstudio_url": {
                    "type": "string",
                    "description": "LM Studio API base URL. Default: http://localhost:1234",
                    "default": "http://localhost:1234"
                },
                "tools": {
                    "type": "array",
                    "description": (
                        "JSON array of MCP tool name strings to give this agent access to. "
                        "Must be a JSON array of strings, not a comma-separated string. "
                        "Example: [\"shell_run\", \"fs_list\"]. "
                        "Omit or pass [] for a session without tools."
                    ),
                    "items": {"type": "string"},
                    "default": []
                },
                "max_tool_iterations": {
                    "type": "integer",
                    "description": "Maximum number of tool call rounds per agent turn. Default: 10.",
                    "default": 10
                }
            }
        }
    },
    {
        "name": "selfchat_register_tool",
        "description": (
            "Register an external tool handler so selfchat agents can call it. "
            "You must register each MCP tool you want agents to access. "
            "This is called automatically by the server when tool_registry is provided at init. "
            "Manually call this if you want to add tools at runtime."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "description": "Name of the tool to register (must match an existing MCP tool name)."
                }
            },
            "required": ["tool_name"]
        }
    },
    {
        "name": "selfchat_list_registered_tools",
        "description": "List all MCP tools currently registered and available for selfchat agents to use.",
        "schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "selfchat_send",
        "description": (
            "Send a message to an active self-chat session. "
            "Returns immediately with a job_id — the model runs in the background. "
            "If the session was created with tools, the agent can call them autonomously. "
            "Use selfchat_poll with the job_id to check status and retrieve the reply."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "message": {"type": "string"},
                "temperature": {"type": "number", "default": 0.7},
                "max_tokens": {"type": "integer", "default": 4096}
            },
            "required": ["session_id", "message"]
        }
    },
    {
        "name": "selfchat_send_many",
        "description": (
            "Send messages to multiple self-chat sessions simultaneously. "
            "All run in parallel. Returns immediately with batch_id and job_ids. "
            "Use selfchat_await to wait for all results at once."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "requests": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "session_id": {"type": "string"},
                            "message": {"type": "string"},
                            "temperature": {"type": "number", "default": 0.7},
                            "max_tokens": {"type": "integer", "default": 4096}
                        },
                        "required": ["session_id", "message"]
                    }
                }
            },
            "required": ["requests"]
        }
    },
    {
        "name": "selfchat_poll",
        "description": (
            "Check the status of a background job started by selfchat_send. "
            "Returns status: 'pending' (still running), 'done' (reply ready), or 'error'."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"}
            },
            "required": ["job_id"]
        }
    },
    {
        "name": "selfchat_poll_many",
        "description": (
            "Check the status of all jobs in a batch started by selfchat_send_many. "
            "Returns per-job status and a pending count. Poll until pending=0."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "batch_id": {"type": "string"}
            },
            "required": ["batch_id"]
        }
    },
    {
        "name": "selfchat_await",
        "description": (
            "Wait until all jobs in a batch are complete, then return all results at once. "
            "Preferred over manual selfchat_poll_many loops. "
            "Blocks internally until pending=0 or timeout is reached."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "batch_id": {"type": "string"},
                "timeout": {"type": "number", "default": 600},
                "poll_interval": {"type": "number", "default": 5}
            },
            "required": ["batch_id"]
        }
    },
    {
        "name": "selfchat_wait",
        "description": (
            "Sleep for a given number of seconds. "
            "Use this between selfchat_poll calls. "
            "Do NOT use browser tools as a timer — use this instead."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "seconds": {"type": "number", "default": 10}
            }
        }
    },
    {
        "name": "selfchat_history",
        "description": "Get the full conversation history of a self-chat session, including any tool calls the agent made.",
        "schema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"}
            },
            "required": ["session_id"]
        }
    },
    {
        "name": "selfchat_close",
        "description": "Close and delete a self-chat session, freeing memory.",
        "schema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"}
            },
            "required": ["session_id"]
        }
    },
    {
        "name": "selfchat_list",
        "description": "List all active self-chat sessions with their metadata.",
        "schema": {
            "type": "object",
            "properties": {}
        }
    }
]

_executor = ThreadPoolExecutor(max_workers=16)

_TOOL_CALL_PREFIX = "TOOL_CALL:"

_AGENT_TOOL_INSTRUCTIONS = """
You have access to real MCP tools. To call a tool, output exactly this on its own line:
TOOL_CALL: tool_name {"arg1": "value1", "arg2": "value2"}

Rules:
- The TOOL_CALL line must be the only content in your response when calling a tool.
- After the tool result is returned, continue your reasoning.
- You may call tools multiple times before giving your final answer.
- When you have gathered all needed information, respond normally without a TOOL_CALL line.
- Never fabricate tool results. If a tool fails, say so.

Available tools:
{tool_list}
"""


class SelfChatTools:
    def __init__(self, tool_registry: dict | None = None):
        self._sessions: dict[str, dict] = {}
        self._jobs: dict[str, dict] = {}
        self._batches: dict[str, dict] = {}
        self._tool_registry: dict[str, callable] = tool_registry or {}

    def set_tool_registry(self, registry: dict):
        self._tool_registry = registry

    def _get_loaded_model(self, base_url: str) -> str | None:
        candidate_urls = [base_url.rstrip("/")]
        parsed = urllib.parse.urlparse(base_url)
        if parsed.port != 1234:
            candidate_urls.append(f"{parsed.scheme}://{parsed.hostname}:1234")
        if parsed.port != 11434:
            candidate_urls.append(f"{parsed.scheme}://{parsed.hostname}:11434")

        for url in candidate_urls:
            try:
                req = urllib.request.Request(
                    f"{url}/v1/models",
                    headers={"Authorization": "Bearer lm-studio"},
                    method="GET"
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    models = data.get("data", [])
                    if models:
                        return models[0]["id"]
            except Exception:
                pass

        for url in candidate_urls:
            try:
                req = urllib.request.Request(
                    f"{url}/api/tags",
                    method="GET"
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    models = data.get("models", [])
                    if models:
                        return models[0].get("name") or models[0].get("id")
            except Exception:
                pass

        return None

    def _call_api_blocking(self, base_url: str, payload: dict, token_callback=None) -> dict:
        parsed = urllib.parse.urlparse(base_url.rstrip("/"))
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        path = (parsed.path.rstrip("/") or "") + "/v1/chat/completions"

        streaming_payload = dict(payload)
        streaming_payload["stream"] = True

        body = json.dumps(streaming_payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer lm-studio",
            "Content-Length": str(len(body)),
        }

        try:
            if parsed.scheme == "https":
                conn = http.client.HTTPSConnection(host, port, timeout=30)
            else:
                conn = http.client.HTTPConnection(host, port, timeout=30)

            conn.request("POST", path, body=body, headers=headers)
            resp = conn.getresponse()

            if resp.status != 200:
                error_body = resp.read().decode("utf-8", errors="replace")
                conn.close()
                return {"error": f"HTTP {resp.status}: {error_body}"}

            chunks = []
            finish_reason = "unknown"

            while True:
                line = resp.readline()
                if not line:
                    break
                line = line.decode("utf-8").strip()
                if not line:
                    continue
                if line == "data: [DONE]":
                    break
                if not line.startswith("data: "):
                    continue
                raw = line[6:]
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                delta = event.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content")
                if content:
                    chunks.append(content)
                    if token_callback:
                        token_callback(content)
                fr = event.get("choices", [{}])[0].get("finish_reason")
                if fr:
                    finish_reason = fr

            conn.close()
            full_content = "".join(chunks)
            return {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": full_content},
                        "finish_reason": finish_reason,
                    }
                ]
            }

        except Exception as e:
            return {"error": str(e)}

    async def _call_api(self, base_url: str, payload: dict, token_callback=None) -> dict:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            _executor, self._call_api_blocking, base_url, payload, token_callback
        )

    def _parse_tool_call(self, text: str) -> tuple[str, dict] | None:
        for line in text.strip().splitlines():
            line = line.strip()
            if line.startswith(_TOOL_CALL_PREFIX):
                rest = line[len(_TOOL_CALL_PREFIX):].strip()
                parts = rest.split(None, 1)
                tool_name = parts[0] if parts else ""
                raw_args = parts[1] if len(parts) > 1 else "{}"
                try:
                    args = json.loads(raw_args)
                except json.JSONDecodeError:
                    args = {}
                return tool_name, args
        return None

    async def _dispatch_tool(self, tool_name: str, args: dict, allowed_tools: list[str]) -> str:
        if tool_name not in allowed_tools:
            return json.dumps({"error": f"Tool '{tool_name}' is not in the allowed list for this session."})
        handler = self._tool_registry.get(tool_name)
        if not handler:
            return json.dumps({"error": f"Tool '{tool_name}' is not registered. Available: {list(self._tool_registry.keys())}"})
        try:
            result = await handler(args)
            if isinstance(result, str):
                return result
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": f"Tool '{tool_name}' raised an exception: {e}"})

    async def _run_job(self, job_id: str, session_id: str, message: str, temperature: float, max_tokens: int):
        job = self._jobs[job_id]
        session = self._sessions.get(session_id)
        if not session:
            job["status"] = "error"
            job["error"] = f"Session '{session_id}' not found."
            return

        allowed_tools: list[str] = session.get("tools", [])
        max_iterations: int = session.get("max_tool_iterations", 10)

        async with session["lock"]:
            session["messages"].append({"role": "user", "content": message})

        final_reply = ""
        finish_reason = "unknown"
        tool_calls_made = []

        term = _debug.DebugTerminal(f"[selfchat {session_id}]")
        if _debug.DEBUG:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(_executor, term.open)
        term.writeln(f"=== session {session_id}  model: {session['model']} ===")
        term.writeln(f"USER: {message}")
        term.writeln()

        for iteration in range(max_iterations + 1):
            async with session["lock"]:
                payload = {
                    "model": session["model"],
                    "messages": list(session["messages"]),
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }

            term.write(f"AGENT [iter {iteration}]: ")

            def on_token(tok: str, _term=term):
                _term.write(tok)

            result = await self._call_api(
                session["base_url"], payload,
                token_callback=on_token if _debug.DEBUG else None
            )
            term.writeln()

            if "error" in result:
                term.writeln(f"ERROR: {result['error']}")
                term.close()
                async with session["lock"]:
                    session["messages"].pop()
                job["status"] = "error"
                job["error"] = result["error"]
                return

            try:
                choice = result["choices"][0]
                reply = choice["message"].get("content") or ""
                finish_reason = choice.get("finish_reason", "unknown")
            except (KeyError, IndexError, TypeError) as e:
                term.writeln(f"ERROR: bad API response: {e}")
                term.close()
                async with session["lock"]:
                    session["messages"].pop()
                job["status"] = "error"
                job["error"] = f"Unexpected API response structure: {e}"
                return

            if not reply:
                term.writeln("ERROR: empty content from model.")
                term.close()
                async with session["lock"]:
                    session["messages"].pop()
                job["status"] = "error"
                job["error"] = "Model returned empty content."
                return

            parsed = self._parse_tool_call(reply) if allowed_tools else None

            if parsed is not None and iteration < max_iterations:
                tool_name, tool_args = parsed
                term.writeln(f"TOOL_CALL: {tool_name} {tool_args}")
                tool_result = await self._dispatch_tool(tool_name, tool_args, allowed_tools)
                result_preview = tool_result if len(tool_result) <= 500 else tool_result[:500] + "...(truncated)"
                term.writeln(f"TOOL_RESULT: {result_preview}")
                term.writeln()

                tool_calls_made.append({"tool": tool_name, "args": tool_args, "result": tool_result})

                async with session["lock"]:
                    session["messages"].append({"role": "assistant", "content": reply})
                    session["messages"].append({
                        "role": "user",
                        "content": f"TOOL_RESULT: {tool_name}\n{tool_result}"
                    })
                continue

            final_reply = reply
            break

        if not final_reply:
            final_reply = reply

        async with session["lock"]:
            session["messages"].append({"role": "assistant", "content": final_reply})
            session["turn_count"] += 1
            turn = session["turn_count"]
            total = len(session["messages"])

        term.writeln()
        term.writeln(f"=== done  turn={turn}  finish={finish_reason} ===")
        term.close()

        job["status"] = "done"
        job["result"] = {
            "session_id": session_id,
            "turn": turn,
            "reply": final_reply,
            "finish_reason": finish_reason,
            "model": session["model"],
            "total_messages": total,
            "tool_calls": tool_calls_made
        }

    async def _create(self, args: dict) -> dict:
        base_url = args.get("lmstudio_url", "http://localhost:1234")
        system_prompt = args.get("system_prompt", "")
        model = args.get("model") or self._get_loaded_model(base_url) or "local-model"

        allowed_tools = args.get("tools", [])
        if isinstance(allowed_tools, str):
            try:
                allowed_tools = json.loads(allowed_tools)
            except json.JSONDecodeError:
                allowed_tools = [t.strip() for t in allowed_tools.replace(",", " ").split() if t.strip()]
        if not isinstance(allowed_tools, list):
            allowed_tools = []
        max_tool_iterations = int(args.get("max_tool_iterations", 10))

        unavailable = [t for t in allowed_tools if t not in self._tool_registry]
        if unavailable:
            return {"error": f"Tools not registered: {unavailable}. Call selfchat_list_registered_tools to see available tools."}

        session_id = str(uuid.uuid4())[:8]
        messages = []

        full_system = system_prompt or ""
        if allowed_tools:
            tool_list_str = "\n".join(
                f"- {t}" for t in allowed_tools
            )
            tool_instructions = _AGENT_TOOL_INSTRUCTIONS.format(tool_list=tool_list_str)
            full_system = (full_system + "\n\n" + tool_instructions).strip()

        if full_system:
            messages.append({"role": "system", "content": full_system})

        self._sessions[session_id] = {
            "session_id": session_id,
            "model": model,
            "base_url": base_url,
            "system_prompt": full_system,
            "messages": messages,
            "created_at": datetime.now().isoformat(),
            "turn_count": 0,
            "lock": asyncio.Lock(),
            "tools": allowed_tools,
            "max_tool_iterations": max_tool_iterations
        }

        return {
            "session_id": session_id,
            "model": model,
            "tools": allowed_tools,
            "max_tool_iterations": max_tool_iterations,
            "status": "ready",
            "note": "Agent can now call real MCP tools autonomously using TOOL_CALL: syntax."
            if allowed_tools else "Use selfchat_send with this session_id to talk to the inner model."
        }

    async def _register_tool(self, args: dict) -> dict:
        tool_name = args.get("tool_name", "")
        if not tool_name:
            return {"error": "tool_name is required."}
        if tool_name not in self._tool_registry:
            return {"error": f"Tool '{tool_name}' not found in registry. It must be registered at server startup via set_tool_registry()."}
        return {"registered": tool_name, "status": "ok"}

    async def _list_registered_tools(self, args: dict) -> dict:
        return {
            "tools": sorted(self._tool_registry.keys()),
            "count": len(self._tool_registry)
        }

    async def _send(self, args: dict) -> dict:
        session_id = args["session_id"]
        message = args["message"]
        temperature = args.get("temperature", 0.7)
        max_tokens = args.get("max_tokens", 4096)

        if session_id not in self._sessions:
            return {"error": f"Session '{session_id}' not found. Create one with selfchat_create."}

        job_id = str(uuid.uuid4())[:8]
        self._jobs[job_id] = {
            "job_id": job_id,
            "session_id": session_id,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "result": None,
            "error": None
        }

        asyncio.ensure_future(self._run_job(job_id, session_id, message, temperature, max_tokens))

        return {
            "job_id": job_id,
            "session_id": session_id,
            "status": "pending",
            "note": "Job started in background. Use selfchat_poll with job_id to get the reply."
        }

    async def _send_many(self, args: dict) -> dict:
        requests_list = args.get("requests", [])
        if not requests_list:
            return {"error": "No requests provided."}

        batch_id = str(uuid.uuid4())[:8]
        job_ids = []

        for r in requests_list:
            session_id = r["session_id"]
            job_id = str(uuid.uuid4())[:8]
            if session_id not in self._sessions:
                self._jobs[job_id] = {
                    "job_id": job_id,
                    "session_id": session_id,
                    "status": "error",
                    "created_at": datetime.now().isoformat(),
                    "result": None,
                    "error": f"Session '{session_id}' not found."
                }
            else:
                self._jobs[job_id] = {
                    "job_id": job_id,
                    "session_id": session_id,
                    "status": "pending",
                    "created_at": datetime.now().isoformat(),
                    "result": None,
                    "error": None
                }
                asyncio.ensure_future(self._run_job(
                    job_id,
                    session_id,
                    r["message"],
                    r.get("temperature", 0.7),
                    r.get("max_tokens", 4096)
                ))
            job_ids.append(job_id)

        self._batches[batch_id] = {
            "batch_id": batch_id,
            "job_ids": job_ids,
            "created_at": datetime.now().isoformat()
        }

        return {
            "batch_id": batch_id,
            "job_ids": job_ids,
            "count": len(job_ids),
            "status": "pending",
            "note": "All jobs started in background. Use selfchat_await with batch_id to get all replies."
        }

    async def _poll(self, args: dict) -> dict:
        job_id = args["job_id"]
        job = self._jobs.get(job_id)
        if not job:
            return {"error": f"Job '{job_id}' not found."}
        if job["status"] == "pending":
            return {"job_id": job_id, "status": "pending", "note": "Still running. Poll again in a moment."}
        if job["status"] == "error":
            return {"job_id": job_id, "status": "error", "error": job["error"]}
        return {"job_id": job_id, "status": "done", **job["result"]}

    async def _poll_many(self, args: dict) -> dict:
        batch_id = args["batch_id"]
        batch = self._batches.get(batch_id)
        if not batch:
            return {"error": f"Batch '{batch_id}' not found."}

        results = []
        pending_count = 0
        for job_id in batch["job_ids"]:
            job = self._jobs.get(job_id)
            if not job:
                results.append({"job_id": job_id, "status": "error", "error": "Job not found."})
                continue
            if job["status"] == "pending":
                pending_count += 1
                results.append({"job_id": job_id, "session_id": job["session_id"], "status": "pending"})
            elif job["status"] == "error":
                results.append({"job_id": job_id, "session_id": job["session_id"], "status": "error", "error": job["error"]})
            else:
                results.append({"job_id": job_id, "status": "done", **job["result"]})

        return {
            "batch_id": batch_id,
            "results": results,
            "total": len(results),
            "pending": pending_count,
            "done": len(results) - pending_count
        }

    async def _wait(self, args: dict) -> dict:
        seconds = float(args.get("seconds", 10))
        seconds = max(1.0, min(seconds, 120.0))
        await asyncio.sleep(seconds)
        return {"slept_seconds": seconds, "status": "done"}

    async def _await_batch(self, args: dict) -> dict:
        batch_id = args["batch_id"]
        timeout = float(args.get("timeout", 600))
        poll_interval = float(args.get("poll_interval", 5))
        poll_interval = max(1.0, min(poll_interval, 30.0))

        batch = self._batches.get(batch_id)
        if not batch:
            return {"error": f"Batch '{batch_id}' not found."}

        deadline = asyncio.get_event_loop().time() + timeout
        elapsed = 0.0

        while True:
            results = []
            pending_count = 0
            for job_id in batch["job_ids"]:
                job = self._jobs.get(job_id)
                if not job:
                    results.append({"job_id": job_id, "status": "error", "error": "Job not found."})
                    continue
                if job["status"] == "pending":
                    pending_count += 1
                    results.append({"job_id": job_id, "session_id": job["session_id"], "status": "pending"})
                elif job["status"] == "error":
                    results.append({"job_id": job_id, "session_id": job["session_id"], "status": "error", "error": job["error"]})
                else:
                    results.append({"job_id": job_id, "status": "done", **job["result"]})

            if pending_count == 0:
                return {
                    "batch_id": batch_id,
                    "results": results,
                    "total": len(results),
                    "pending": 0,
                    "done": len(results),
                    "elapsed_seconds": round(elapsed, 1),
                    "timed_out": False
                }

            if asyncio.get_event_loop().time() >= deadline:
                return {
                    "batch_id": batch_id,
                    "results": results,
                    "total": len(results),
                    "pending": pending_count,
                    "done": len(results) - pending_count,
                    "elapsed_seconds": round(elapsed, 1),
                    "timed_out": True,
                    "note": f"{pending_count} job(s) still running after {timeout}s timeout."
                }

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

    async def _history(self, args: dict) -> dict:
        session_id = args["session_id"]
        session = self._sessions.get(session_id)
        if not session:
            return {"error": f"Session '{session_id}' not found."}
        return {
            "session_id": session_id,
            "model": session["model"],
            "created_at": session["created_at"],
            "turn_count": session["turn_count"],
            "tools": session.get("tools", []),
            "messages": session["messages"]
        }

    async def _close(self, args: dict) -> dict:
        session_id = args["session_id"]
        if session_id not in self._sessions:
            return {"error": f"Session '{session_id}' not found."}
        session = self._sessions.pop(session_id)
        return {
            "closed": session_id,
            "model": session["model"],
            "turns": session["turn_count"]
        }

    async def _list(self, args: dict) -> dict:
        sessions = [
            {
                "session_id": s["session_id"],
                "model": s["model"],
                "created_at": s["created_at"],
                "turn_count": s["turn_count"],
                "total_messages": len(s["messages"]),
                "tools": s.get("tools", [])
            }
            for s in self._sessions.values()
        ]
        return {"sessions": sessions, "count": len(sessions)}

    def get_handlers(self):
        return {
            "selfchat_create": self._create,
            "selfchat_register_tool": self._register_tool,
            "selfchat_list_registered_tools": self._list_registered_tools,
            "selfchat_send": self._send,
            "selfchat_send_many": self._send_many,
            "selfchat_poll": self._poll,
            "selfchat_poll_many": self._poll_many,
            "selfchat_await": self._await_batch,
            "selfchat_wait": self._wait,
            "selfchat_history": self._history,
            "selfchat_close": self._close,
            "selfchat_list": self._list,
        }