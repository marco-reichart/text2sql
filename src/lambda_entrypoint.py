import json
import logging
import time
from pathlib import Path

from common.llm import record_llm_calls
from common.runtime_context import set_llm_type
from config.config_loader import ConfigLoader
from text2sql.graph import Settings, text2sql

ConfigLoader.initialize(config_path=str(Path(__file__).parent / "config" / "config.yaml"))
logging.basicConfig(
    level=getattr(logging, "INFO", logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("text2sql")
logger.setLevel(getattr(logging, "INFO", logging.INFO))


def _response(status_code: int, body: dict) -> dict:
    return {"statusCode": status_code, "body": json.dumps(body, default=str)}


def _settings(event: dict) -> Settings:
    max_corrections = int(event.get("max_corrections", 2))
    if not 0 <= max_corrections <= 5:
        raise ValueError("max_corrections must be between 0 and 5")
    return Settings(
        check_with_llm=bool(event.get("check_with_llm", True)),
        max_corrections=max_corrections,
        explain=bool(event.get("explain", True)),
    )


def lambda_handler(event, context=None):
    """Start processing here.

    Event: {"question": "...", "db_id": "...", optional "llm_type", "check_with_llm", "max_corrections",
    "explain", "max_rows"}.
    """
    logger.info(f"Received event: {event}")
    try:
        config = ConfigLoader.get()
        question, db_id = event.get("question"), event.get("db_id")
        if not question or not db_id:
            return _response(400, {"error": "question and db_id are required"})
        llm_type = event.get("llm_type") or config["default_llm_type"]
        if llm_type not in config["llms"]:
            return _response(400, {"error": f"Unknown llm_type: {llm_type}"})
        set_llm_type(llm_type)
        settings = _settings(event)
        max_rows = int(event.get("max_rows", 1000))

        start = time.perf_counter()
        with record_llm_calls() as calls:
            out = text2sql(question, db_id, settings)
        rows = out.get("rows", [])
        body = {
            "sql": out.get("sql", ""),
            "columns": out.get("columns", []),
            "rows": rows[:max_rows],
            "truncated": len(rows) > max_rows,
            "answer": out.get("answer"),
            "failed": out.get("failed", False),
            "errors": out.get("errors", []),
            "attempts": out.get("attempts", 0),
            "llm_type": llm_type,
            "llm_calls": len(calls),
            "latency_s": round(time.perf_counter() - start, 3),
            "steps": calls,
        }
        logger.info(json.dumps({k: body[k] for k in ("sql", "failed", "attempts", "llm_calls", "latency_s")}))
        return _response(200, body)
    except FileNotFoundError:
        return _response(404, {"error": f"Unknown database: {event.get('db_id')}"})
    except ValueError as e:
        return _response(400, {"error": str(e)})
    except Exception as e:
        logger.error(f"Error processing request: {e}")
        return _response(500, {"error": str(e)})
