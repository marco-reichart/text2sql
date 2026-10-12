"""Values that are set once per invocation (one request at a time per Lambda instance)."""

_runtime = {"llm_type": ""}


def set_llm_type(llm_type: str) -> None:
    _runtime["llm_type"] = llm_type


def get_llm_type() -> str:
    llm_type = _runtime.get("llm_type")
    if not llm_type:
        raise RuntimeError("llm_type not set in runtime context")
    return llm_type
