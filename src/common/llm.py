"""Helper functions for LLM inference."""

import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import cache

from langgraph.config import get_config

from common.runtime_context import get_llm_type
from config.config_loader import ConfigLoader

_calls: ContextVar[list[dict] | None] = ContextVar("llm_calls", default=None)


@contextmanager
def record_llm_calls() -> Iterator[list[dict]]:
    """Collect every LLM call made inside the `with` block."""
    calls: list[dict] = []
    token = _calls.set(calls)
    try:
        yield calls
    finally:
        _calls.reset(token)


def _current_node() -> str:
    """Name of the graph node that is calling the LLM, or "direct" when called outside the graph."""
    try:
        return get_config()["metadata"]["langgraph_node"]
    except (RuntimeError, KeyError):
        return "direct"


@cache
def _ollama_client(host: str):
    import ollama

    return ollama.Client(host=host)


@cache
def _bedrock_client(region: str):
    import boto3

    return boto3.client("bedrock-runtime", region_name=region)


def _ask_ollama(llm: dict, system: str, prompt: str) -> tuple[str, int, int]:
    response = _ollama_client(llm["host"]).chat(
        model=llm["model_id"],
        messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        think=False,
        options={"temperature": llm["temperature"], "num_predict": llm["max_tokens"]},
    )
    return response.message.content, response.prompt_eval_count or 0, response.eval_count or 0


def _ask_bedrock(llm: dict, system: str, prompt: str) -> tuple[str, int, int]:
    if "qwen3" in llm["model_id"]:
        prompt += "\n/no_think"  # Qwen3 switch: answer directly, without reasoning tokens
    response = _bedrock_client(ConfigLoader.get()["awsRegion"]).converse(
        modelId=llm["model_id"],
        system=[{"text": system}],
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"temperature": llm["temperature"], "maxTokens": llm["max_tokens"]},
    )
    text = "".join(block["text"] for block in response["output"]["message"]["content"] if "text" in block)
    return text, response["usage"]["inputTokens"], response["usage"]["outputTokens"]


def ask(system: str, prompt: str) -> str:
    llm = ConfigLoader.get()["llms"][get_llm_type()]
    start = time.perf_counter()
    if llm["provider"] == "bedrock":
        text, input_tokens, output_tokens = _ask_bedrock(llm, system, prompt)
    else:
        text, input_tokens, output_tokens = _ask_ollama(llm, system, prompt)
    output = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()

    calls = _calls.get()
    if calls is not None:
        calls.append(
            {
                "node": _current_node(),
                "seconds": round(time.perf_counter() - start, 3),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "output": output,
            }
        )
    return output
