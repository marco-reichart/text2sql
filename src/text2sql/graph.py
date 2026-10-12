"""The Text2SQL LangGraph workflow: generator -> validator -> executor -> checker -> (corrector) -> explainer."""

import re
import sqlite3
from dataclasses import dataclass
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from common.llm import ask
from text2sql.db import execute_sql, get_schema, validate_sql

MAX_PROMPT_ROWS = 50  # rows shown to the LLM (explainer); the executor keeps all rows
MAX_CHECK_ROWS = 20  # rows shown to the LLM judge in the checker

SQL_GENERATOR_PROMPT = """
You are a text-to-SQL specialist.

Your task is to translate a natural-language question into
a correct SQLite SQL query.

Rules:

1. Only generate SELECT statements.
2. Use only tables and columns present in the provided schema.
3. Do not invent tables or columns.
4. Prefer simple SQL when possible.
5. Return ONLY the SQL query.
6. Do not use markdown code fences.
7. Do not explain your answer.
"""

CHECKER_PROMPT = """
Your task is to verify whether a SQL query and its result correctly answer the question of the user.

Rules:
1. Reply with exactly `OK` if they do. Otherwise reply `WRONG: <one sentence naming the mistake>`.
2. Only flag clear mistakes: wrong or missing columns, missing or wrong filter, wrong aggregation, wrong join,
wrong ordering or limit.
3. When in doubt, reply `OK`.
"""

EXPLAINER_PROMPT = """
You explain SQL query results to users.

Rules:
1. Only describe facts supported by the query result.
2. Do not invent information.
3. Be concise.
4. Mention important numbers and trends.
5. If there are no rows, explicitly say so.
"""


@dataclass(frozen=True)
class Settings:
    """Per-run settings, passed to the graph as runtime context."""

    check_with_llm: bool = True  # LLM judge in the checker; False = only deterministic checks
    max_corrections: int = 2  # total corrector runs (invalid SQL + wrong results), then -> failure / give_up
    explain: bool = True  # run the explainer at the end


class State(TypedDict, total=False):
    # input
    question: str
    db_id: str
    schema: str
    # working state
    sql: str
    errors: list[str]
    attempts: int
    columns: list[str]
    rows: list[tuple]  # full result
    exec_error: str | None
    confirmed: bool  # corrector returned the query unchanged -> accept it
    # output
    answer: str | None
    failed: bool


def create_prompt(question: str, schema: str) -> str:
    return f"""
Database schema:
{schema}

User question:
{question}
"""


def clean_sql(text: str) -> str:
    """Remove markdown code fences, in case the model adds them anyway."""
    fenced = re.search(r"```(?:sql)?\s*(.*?)```", text, flags=re.S | re.I)
    return (fenced.group(1) if fenced else text).strip()


def format_rows(columns: list[str], rows: list[tuple], limit: int = MAX_PROMPT_ROWS) -> str:
    """Render rows for an LLM prompt: at most `limit` rows, plus the total so the LLM knows what it doesn't see."""
    lines = [" | ".join(columns)] + [" | ".join(map(str, r)) for r in rows[:limit]]
    if len(rows) > limit:
        lines.append(f"... showing {limit} of {len(rows)} rows")
    return "\n".join(lines)


# --- nodes ---------------------------------------------------------------------------------------------------


def generate(state: State) -> State:
    prompt = create_prompt(state["question"], state["schema"])
    return {"sql": clean_sql(ask(SQL_GENERATOR_PROMPT, prompt))}


def validate(state: State) -> State:
    return {"errors": validate_sql(state["sql"], state["db_id"])}


def correct(state: State) -> State:
    problems = "\n".join(state["errors"])
    prompt = (
        create_prompt(state["question"], state["schema"])
        + f"\nGenerated query: {state['sql']}\n\nProblems: {problems}\n"
    )
    new_sql = clean_sql(ask(SQL_GENERATOR_PROMPT, prompt))
    unchanged = " ".join(new_sql.split()).rstrip(";") == " ".join(state["sql"].split()).rstrip(";")
    return {"sql": new_sql, "attempts": state["attempts"] + 1, "confirmed": unchanged}


def execute(state: State) -> State:
    try:
        columns, rows = execute_sql(state["sql"], state["db_id"])
    except sqlite3.Error as e:  # e.g. timeout ("interrupted") -> checker sends it to the corrector
        return {"columns": [], "rows": [], "exec_error": str(e)}
    return {"columns": columns, "rows": rows, "exec_error": None}


def check(state: State, runtime: Runtime[Settings]) -> State:
    """Catch valid-but-wrong queries. Cheap deterministic checks first, then the optional LLM judge."""
    if state["exec_error"]:
        return {"errors": [f"Execution error: {state['exec_error']}"]}
    if state.get("confirmed"):  # the corrector kept the query as it was -> trust it
        return {"errors": []}
    if not state["rows"]:
        return {
            "errors": [
                "The query returned no rows. Check filter values (spelling, case, format) and join conditions. "
                "If no rows is really the correct answer, return the query unchanged."
            ]
        }
    if all(value is None for row in state["rows"] for value in row):
        return {"errors": ["The query returned only NULL values."]}
    if not runtime.context.check_with_llm:
        return {"errors": []}

    result = format_rows(state["columns"], state["rows"], limit=MAX_CHECK_ROWS)
    prompt = (
        create_prompt(state["question"], state["schema"]) + f"\nGenerated query: {state['sql']}\n\nResult: {result}\n"
    )
    verdict = ask(CHECKER_PROMPT, prompt)
    return {"errors": [] if verdict.strip("`*. ").upper().startswith("OK") else [verdict]}


def explain(state: State) -> State:
    result = format_rows(state["columns"], state["rows"])
    prompt = f"Question: {state['question']}\n\nGenerated query: {state['sql']}\n\nResult: {result}\n"
    if state["errors"]:  # reached via give_up
        prompt += "\nNote: a reviewer suspects this result is wrong: " + " ".join(state["errors"])
        prompt += "\nAnswer from the result, but tell the user it may be inaccurate."
    return {"answer": ask(EXPLAINER_PROMPT, prompt)}


def fail(state: State) -> State:
    return {
        "answer": f"Could not produce a working query after {state['attempts']} corrections: {state['errors']}",
        "failed": True,
    }


# --- routing and graph ---------------------------------------------------------------------------------------


def route_after_validate(state: State, runtime: Runtime[Settings]) -> str:
    if not state["errors"]:
        return "executor"
    return "corrector" if state["attempts"] < runtime.context.max_corrections else "failure"


def route_after_check(state: State, runtime: Runtime[Settings]) -> str:
    done = "explainer" if runtime.context.explain else END
    if not state["errors"]:
        return done
    if state["attempts"] < runtime.context.max_corrections:
        return "corrector"
    # budget used up: answer with a caveat if we have data (give_up), otherwise fail
    return done if state["rows"] else "failure"


def build_graph():
    builder = StateGraph(State, context_schema=Settings)
    builder.add_node("generator", generate)
    builder.add_node("validator", validate)
    builder.add_node("corrector", correct)
    builder.add_node("executor", execute)
    builder.add_node("checker", check)
    builder.add_node("explainer", explain)
    builder.add_node("failure", fail)

    builder.add_edge(START, "generator")
    builder.add_edge("generator", "validator")
    builder.add_conditional_edges("validator", route_after_validate, ["executor", "corrector", "failure"])
    builder.add_edge("corrector", "validator")
    builder.add_edge("executor", "checker")
    builder.add_conditional_edges("checker", route_after_check, ["explainer", "corrector", "failure", END])
    builder.add_edge("explainer", END)
    builder.add_edge("failure", END)
    return builder.compile()


graph = build_graph()


def text2sql(question: str, db_id: str, settings: Settings | None = None) -> State:
    """Run the graph for one question, e.g. `text2sql(q, db, Settings(check_with_llm=False, explain=False))`."""
    settings = settings or Settings()  # not a default argument: ruff B008
    return graph.invoke(
        {
            "question": question,
            "db_id": db_id,
            "schema": get_schema(db_id),
            "attempts": 0,
            "answer": None,
            "failed": False,
        },
        context=settings,
        # each correction adds at most 4 steps; LangGraph's default limit (25) would cap max_corrections at 5
        config={"recursion_limit": 4 * settings.max_corrections + 10},
    )
