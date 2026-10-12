"""Run the Text2SQL Lambda handler locally, or invoke the deployed Lambda function.

Local (Ollama):  uv run python src/run_text2sql.py --question "How many singers do we have?" --db-id concert_singer
AWS:             uv run python src/run_text2sql.py --question "..." --db-id concert_singer \
                     --function-name <lambda function name> --llm-type qwen3_32b
"""

import argparse
import json
import logging

logging.basicConfig(
    level=getattr(logging, "INFO", logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("text2sql")
logger.setLevel(getattr(logging, "INFO", logging.INFO))


def build_event(question: str, db_id: str, llm_type: str, check_with_llm: bool, max_corrections: int, explain: bool):
    return {
        "question": question,
        "db_id": db_id,
        "llm_type": llm_type,
        "check_with_llm": check_with_llm,
        "max_corrections": max_corrections,
        "explain": explain,
    }


def invoke_lambda(function_name: str, event: dict, region: str = "eu-central-1") -> dict:
    """Invoke the deployed Lambda function and return its response ({"statusCode", "body"})."""
    import boto3
    from botocore.config import Config

    client = boto3.client("lambda", region_name=region, config=Config(read_timeout=300))
    response = client.invoke(FunctionName=function_name, Payload=json.dumps(event).encode())
    return json.loads(response["Payload"].read())


def main() -> None:
    parser = argparse.ArgumentParser(description="Run text2sql locally or on AWS Lambda")
    parser.add_argument("--question", required=True, help="Question in plain English")
    parser.add_argument("--db-id", required=True, help="Spider database id, e.g. concert_singer")
    parser.add_argument("--llm-type", default="ollama", help="LLM from config.yaml (default: ollama)")
    parser.add_argument("--no-judge", action="store_true", help="Skip the LLM judge in the checker")
    parser.add_argument("--max-corrections", type=int, default=2)
    parser.add_argument("--no-explain", action="store_true", help="Skip the explainer")
    parser.add_argument("--function-name", default=None, help="Invoke this deployed Lambda instead of running locally")
    args = parser.parse_args()

    event = build_event(
        question=args.question,
        db_id=args.db_id,
        llm_type=args.llm_type,
        check_with_llm=not args.no_judge,
        max_corrections=args.max_corrections,
        explain=not args.no_explain,
    )
    if args.function_name:
        result = invoke_lambda(args.function_name, event)
    else:
        from lambda_entrypoint import lambda_handler

        result = lambda_handler(event, None)

    body = json.loads(result.get("body", "{}"))
    if result.get("statusCode") == 200:
        logger.info(f"SQL: {body['sql']}")
        logger.info(f"ROWS: {body['rows'][:10]}")
        logger.info(f"ANSWER: {body['answer']}")
        logger.info(f"LLM calls: {body['llm_calls']}, latency: {body['latency_s']} s")
    else:
        logger.error(f"Lambda failed ({result.get('statusCode')}): {body.get('error', 'Unknown error')}")


if __name__ == "__main__":
    main()
