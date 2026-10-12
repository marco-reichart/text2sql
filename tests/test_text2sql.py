"""Tests for the text2sql Lambda with a tiny SQLite database and a fake LLM (no Ollama / Bedrock needed)."""

import json
import sqlite3

import boto3
import pytest
import yaml
from moto import mock_aws

import lambda_entrypoint
from common import llm
from common.runtime_context import set_llm_type
from config.config_loader import ConfigLoader
from text2sql import db, graph


@pytest.fixture(autouse=True)
def setup(tmp_path, monkeypatch):
    """A database `shop` and a config pointing to it."""
    (tmp_path / "shop").mkdir()
    conn = sqlite3.connect(tmp_path / "shop" / "shop.sqlite")
    conn.execute("CREATE TABLE product (id INTEGER PRIMARY KEY, name TEXT, price REAL)")
    conn.executemany("INSERT INTO product VALUES (?, ?, ?)", [(1, "tea", 2.5), (2, "coffee", 4.0)])
    conn.commit()
    conn.close()

    config = {
        "awsRegion": "eu-central-1",
        "default_llm_type": "ollama",
        "databases": {"local_dir": str(tmp_path), "s3_prefix": "databases/", "query_timeout_s": 5},
        "llms": {"ollama": {"provider": "ollama", "host": "x", "model_id": "x", "max_tokens": 10, "temperature": 0}},
    }
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.safe_dump(config), encoding="utf-8")
    ConfigLoader._initialized = False
    ConfigLoader.initialize(config_path=str(config_file))
    set_llm_type("ollama")
    monkeypatch.delenv("DATABASE_BUCKET", raising=False)
    monkeypatch.setattr(db, "TMP_DIR", tmp_path / "downloads")
    db.get_schema.cache_clear()
    yield
    ConfigLoader._config = {}
    ConfigLoader._initialized = False


def fake_llm(monkeypatch, answers: dict[str, list[str]]):
    """`answers` maps a node name to the outputs it returns, in order."""

    def chat(llm_config, system, prompt):
        return answers[llm._current_node()].pop(0), 10, 5

    monkeypatch.setattr(llm, "_ask_ollama", chat)


def test_validate_sql():
    assert db.validate_sql("SELECT name FROM product", "shop") == []
    assert db.validate_sql("DELETE FROM product", "shop") == ["Only SELECT queries are allowed."]
    assert db.validate_sql("SELECT nme FROM product", "shop")[0].startswith("SQLite error")


def test_database_path_rejects_paths():
    with pytest.raises(FileNotFoundError):
        db.database_path("../shop")


def test_happy_path(monkeypatch):
    fake_llm(monkeypatch, {"generator": ["SELECT count(*) FROM product"], "checker": ["OK"], "explainer": ["2"]})
    with llm.record_llm_calls() as calls:
        out = graph.text2sql("How many products?", "shop")
    assert out["rows"] == [(2,)] and out["answer"] == "2" and not out["failed"]
    assert [c["node"] for c in calls] == ["generator", "checker", "explainer"]


def test_correction_and_code_fences(monkeypatch):
    fake_llm(
        monkeypatch,
        {"generator": ["SELECT nme FROM product"], "corrector": ["```sql\nSELECT name FROM product\n```"]},
    )
    out = graph.text2sql("Product names?", "shop", graph.Settings(check_with_llm=False, explain=False))
    assert out["sql"] == "SELECT name FROM product" and out["attempts"] == 1 and out["answer"] is None


def test_empty_result_confirmed_by_corrector(monkeypatch):
    sql = "SELECT name FROM product WHERE price > 100"
    fake_llm(monkeypatch, {"generator": [sql], "corrector": [sql + ";"]})
    out = graph.text2sql("Expensive products?", "shop", graph.Settings(check_with_llm=False, explain=False))
    assert out["rows"] == [] and out["attempts"] == 1 and not out["failed"]


def test_failure_after_max_corrections(monkeypatch):
    fake_llm(monkeypatch, {"generator": ["SELECT x FROM nope"], "corrector": ["SELECT y FROM nope"] * 2})
    out = graph.text2sql("?", "shop", graph.Settings(max_corrections=2))
    assert out["failed"] and out["attempts"] == 2


def test_lambda_handler(monkeypatch):
    fake_llm(monkeypatch, {"generator": ["SELECT name, price FROM product ORDER BY id"], "checker": ["OK"]})
    event = {"question": "All products", "db_id": "shop", "explain": False, "max_rows": 1}
    result = lambda_entrypoint.lambda_handler(event)
    body = json.loads(result["body"])
    assert result["statusCode"] == 200
    assert body["rows"] == [["tea", 2.5]] and body["truncated"] and body["llm_calls"] == 2
    assert [s["node"] for s in body["steps"]] == ["generator", "checker"]


def test_lambda_handler_errors():
    cases = [
        ({"db_id": "shop"}, 400),
        ({"question": "x", "db_id": "unknown"}, 404),
        ({"question": "x", "db_id": "shop", "llm_type": "gpt"}, 400),
        ({"question": "x", "db_id": "shop", "max_corrections": 9}, 400),
    ]
    for event, status_code in cases:
        assert lambda_entrypoint.lambda_handler(event)["statusCode"] == status_code, event


@mock_aws
def test_database_downloaded_from_s3(tmp_path, monkeypatch):
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="code-bucket")
    s3.upload_file(str(tmp_path / "shop" / "shop.sqlite"), "code-bucket", "databases/shop/shop.sqlite")
    monkeypatch.setenv("DATABASE_BUCKET", "code-bucket")

    assert db.database_path("shop") == tmp_path / "downloads" / "shop.sqlite"
    assert db.validate_sql("SELECT name FROM product", "shop") == []
    with pytest.raises(FileNotFoundError):
        db.database_path("unknown")
