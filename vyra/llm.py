"""Provider-swappable LLM layer.

VYRA's brain speaks to one interface — complete(system, messages, tools) —
no matter who is behind it. Switch providers by changing config:
    claude      -> Anthropic SDK (native tool use)
    openrouter  -> OpenAI-compatible endpoint (openrouter.ai)
    google      -> Gemini's OpenAI-compatible endpoint
Any other OpenAI-compatible endpoint works too, via llm.base_url.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class LLMResponse:
    text: str | None = None
    tool_calls: list = field(default_factory=list)  # [{"id", "name", "args", "extra_content"}]


DEFAULT_BASE_URLS = {
    "openrouter": "https://openrouter.ai/api/v1",
    "google": "https://generativelanguage.googleapis.com/v1beta/openai/",
}


def make_client(config: dict):
    llm = config["llm"]
    provider = llm["provider"].lower()
    if provider == "claude":
        return ClaudeAdapter(llm)
    if provider in ("openrouter", "google", "openai"):
        return OpenAICompatAdapter(llm, provider)
    raise SystemExit(f"Unknown provider '{provider}'. Use claude, openrouter, or google.")


class ClaudeAdapter:
    def __init__(self, llm):
        import anthropic
        self.model = llm["model"]
        self.max_tokens = llm.get("max_tokens", 1024)
        kwargs = {"api_key": llm["api_key"]}
        if llm.get("base_url"):
            kwargs["base_url"] = llm["base_url"]
        self.client = anthropic.Anthropic(**kwargs)

    def _tools(self, tools):
        return [{"name": t["name"], "description": t["description"],
                 "input_schema": t["parameters"]} for t in tools]

    def _messages(self, messages):
        out = []
        for m in messages:
            role = m["role"]
            if role == "user":
                out.append({"role": "user", "content": m["content"]})
            elif role == "assistant" and m.get("tool_calls"):
                content = []
                if m.get("content"):
                    content.append({"type": "text", "text": m["content"]})
                for tc in m["tool_calls"]:
                    content.append({"type": "tool_use", "id": tc["id"],
                                    "name": tc["name"], "input": tc["args"]})
                out.append({"role": "assistant", "content": content})
            elif role == "assistant":
                out.append({"role": "assistant", "content": m["content"]})
            elif role == "tool":
                out.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": r["id"], "content": r["output"]}
                    for r in m["results"]]})
        return out

    def complete(self, system, messages, tools):
        kwargs = {"model": self.model, "max_tokens": self.max_tokens,
                  "system": system, "messages": self._messages(messages)}
        if tools:
            kwargs["tools"] = self._tools(tools)
        resp = self.client.messages.create(**kwargs)
        out, texts = LLMResponse(), []
        for block in resp.content:
            if block.type == "text":
                texts.append(block.text)
            elif block.type == "tool_use":
                out.tool_calls.append({"id": block.id, "name": block.name, "args": block.input})
        out.text = "\n".join(texts) if texts else None
        return out


class OpenAICompatAdapter:
    def __init__(self, llm, provider):
        from openai import OpenAI
        self.provider = provider
        self.model = llm["model"]
        self.max_tokens = llm.get("max_tokens", 1024)
        # reasoning_effort is only valid for "low" | "medium" | "high".
        # Never pass "none" or invalid values to endpoints as it triggers 400 Bad Request.
        effort = llm.get("reasoning_effort")
        self.reasoning_effort = effort if effort in ("low", "medium", "high") else None
        base_url = llm.get("base_url") or DEFAULT_BASE_URLS.get(provider)
        self.client = OpenAI(api_key=llm["api_key"], base_url=base_url)

    def _tools(self, tools):
        return [{"type": "function", "function": {
            "name": t["name"], "description": t["description"],
            "parameters": t["parameters"]}} for t in tools]

    def _messages(self, system, messages):
        out = [{"role": "system", "content": system}]
        for m in messages:
            role = m["role"]
            if role == "user":
                out.append({"role": "user", "content": m["content"]})
            elif role == "assistant" and m.get("tool_calls"):
                tc_list = []
                for tc in m["tool_calls"]:
                    item = {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["args"]) if isinstance(tc["args"], dict) else tc["args"]
                        }
                    }
                    if "extra_content" in tc and tc["extra_content"]:
                        item["extra_content"] = tc["extra_content"]
                    tc_list.append(item)
                out.append({"role": "assistant", "content": m.get("content") or None,
                            "tool_calls": tc_list})
            elif role == "assistant":
                out.append({"role": "assistant", "content": m["content"]})
            elif role == "tool":
                for r in m["results"]:
                    out.append({"role": "tool", "tool_call_id": r["id"], "content": r["output"]})
        return out

    def complete(self, system, messages, tools):
        kwargs = {"model": self.model, "max_tokens": self.max_tokens,
                  "messages": self._messages(system, messages)}
        if tools:
            kwargs["tools"] = self._tools(tools)
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort
        resp = self.client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        out = LLMResponse(text=msg.content or None)
        for tc in (msg.tool_calls or []):
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            tc_dict = {"id": tc.id, "name": tc.function.name, "args": args}
            if hasattr(tc, "extra_content") and tc.extra_content:
                tc_dict["extra_content"] = tc.extra_content
            out.tool_calls.append(tc_dict)
        return out
