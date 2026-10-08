"""CLI evaluation harness for benchmarking execution accuracy and repair rates."""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import logging
import os
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import text

from app.config import get_settings
from app.core.db import close_engine, get_engine
from app.core.executor import run as run_sql
from app.core.schema import get_schema_cache
from app.core.table_selector import select_relevant_tables
from app.core.validator import validate as validate_sql
from app.errors import ExecutionError, LLMError, ValidationError
from app.llm.client import OllamaClient
from app.llm.prompts import PROMPT_VERSION
from app.llm.sql_generator import generate as generate_sql
from app.llm.sql_generator import repair as repair_sql

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def normalize_cell(val: Any) -> Any:
    """Normalize cell values for comparison across drivers and types."""
    if val is None:
        return None
    if isinstance(val, (int, float, Decimal)):
        try:
            return round(float(val), 2)
        except Exception:
            return float(val)
    if isinstance(val, (datetime.date, datetime.datetime)):
        return str(val)
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    return str(val).strip()


def normalize_row(row: list[Any] | tuple[Any, ...]) -> tuple[Any, ...]:
    """Normalize row cells into a comparable tuple."""
    return tuple(normalize_cell(c) for c in row)


def compare_result_sets(
    gen_rows: list[list[Any]],
    ref_rows: list[list[Any]],
    order_matters: bool = False,
) -> bool:
    """Compare generated and reference result rows, respecting order_matters."""
    if len(gen_rows) != len(ref_rows):
        return False

    norm_gen = [normalize_row(r) for r in gen_rows]
    norm_ref = [normalize_row(r) for r in ref_rows]

    if order_matters:
        return norm_gen == norm_ref

    # Order-insensitive sort comparison
    return sorted(norm_gen, key=lambda r: tuple(str(x) for x in r)) == sorted(
        norm_ref, key=lambda r: tuple(str(x) for x in r)
    )


async def execute_reference_sql(
    ref_sql: str,
    engine: Any,
) -> list[list[Any]]:
    """Execute reference query directly on engine to get baseline results."""
    async with engine.connect() as conn:
        res = await conn.execute(text(ref_sql))
        rows = res.fetchall()
        return [list(r) for r in rows]


async def evaluate_single_question(
    item: dict[str, Any],
    client: OllamaClient,
    engine: Any,
    schema: Any,
    settings: Any,
) -> dict[str, Any]:
    """Evaluate a single test question end-to-end."""
    q_id = item["id"]
    question = item["question"]
    ref_sql = item["reference_sql"]
    order_matters = item.get("order_matters", False)

    logger.info("Evaluating [%s]: %s", q_id, question)
    t0 = time.perf_counter()

    result_data: dict[str, Any] = {
        "id": q_id,
        "question": question,
        "reference_sql": ref_sql,
        "generated_sql": None,
        "passed": False,
        "repair_attempts": 0,
        "latency_ms": 0.0,
        "error": None,
    }

    # 1. Execute reference SQL baseline
    try:
        ref_rows = await execute_reference_sql(ref_sql, engine)
    except Exception as exc:
        result_data["error"] = f"Reference SQL execution failed: {exc}"
        logger.error("Reference SQL failed on [%s]: %s", q_id, exc)
        return result_data

    # 2. Select relevant tables if large schema
    pruned_schema = select_relevant_tables(schema=schema, question=question, settings=settings)

    # 3. Generate SQL Draft
    try:
        draft = await generate_sql(
            question=question,
            history=[],
            schema=pruned_schema,
            client=client,
            settings=settings,
        )
    except LLMError as exc:
        result_data["error"] = f"LLM Generation failed: {exc}"
        result_data["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        return result_data

    if draft.needs_clarification:
        result_data["error"] = f"Model requested clarification: {draft.clarification_question}"
        result_data["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        return result_data

    current_sql = draft.sql or ""
    result_data["generated_sql"] = current_sql

    # 4. Validation & Repair Loop
    repair_attempt = 0
    safe_sql = None
    exec_result = None

    while repair_attempt <= settings.MAX_REPAIR_ATTEMPTS:
        try:
            safe_sql = validate_sql(current_sql, schema=schema, settings=settings)
        except ValidationError as val_err:
            if repair_attempt < settings.MAX_REPAIR_ATTEMPTS:
                repair_attempt += 1
                try:
                    repaired = await repair_sql(
                        question=question,
                        bad_sql=current_sql,
                        error_msg=str(val_err),
                        schema=schema,
                        client=client,
                        settings=settings,
                    )
                    current_sql = repaired.sql or ""
                    result_data["generated_sql"] = current_sql
                    continue
                except LLMError as rep_exc:
                    result_data["error"] = f"Repair call failed: {rep_exc}"
                    break
            else:
                result_data["error"] = f"Validation failed: {val_err}"
                break

        # Validate succeeded, attempt execute
        assert safe_sql is not None
        try:
            exec_result = await run_sql(safe_sql, engine=engine, settings=settings)
            break
        except ExecutionError as exec_err:
            if repair_attempt < settings.MAX_REPAIR_ATTEMPTS:
                repair_attempt += 1
                try:
                    repaired = await repair_sql(
                        question=question,
                        bad_sql=current_sql,
                        error_msg=str(exec_err),
                        schema=schema,
                        client=client,
                        settings=settings,
                    )
                    current_sql = repaired.sql or ""
                    result_data["generated_sql"] = current_sql
                    continue
                except LLMError as rep_exc:
                    result_data["error"] = f"Repair call failed: {rep_exc}"
                    break
            else:
                result_data["error"] = f"Execution failed: {exec_err}"
                break

    result_data["repair_attempts"] = repair_attempt
    result_data["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)

    if exec_result is not None:
        matches = compare_result_sets(
            gen_rows=exec_result.rows,
            ref_rows=ref_rows,
            order_matters=order_matters,
        )
        result_data["passed"] = matches
        if not matches:
            result_data["error"] = (
                f"Result mismatch: expected {len(ref_rows)} rows, got {len(exec_result.rows)} rows"
            )

    return result_data


async def run_evals(
    model: str,
    questions_path: Path,
    ollama_url: str,
    limit: int | None = None,
    tag: str | None = None,
    db_name: str | None = None,
    db_url: str | None = None,
) -> None:
    """Run evaluation benchmark against configured questions and model."""
    if db_url:
        os.environ["TARGET_DB_URL"] = db_url
        get_settings.cache_clear()
        get_schema_cache().clear()
    elif not db_name and questions_path.name == "questions.yaml":
        current_url = get_settings().TARGET_DB_URL
        if "ecommerce" not in current_url and ":3307" not in current_url:
            fallback = (
                os.environ.get("EVAL_TARGET_DB_URL")
                or "mysql+asyncmy://nl2sql_ro:nl2sql_ro_pass@127.0.0.1:3307/ecommerce"
            )
            logger.info("Using eval ecommerce test container at %s", fallback)
            os.environ["TARGET_DB_URL"] = fallback
            get_settings.cache_clear()
            get_schema_cache().clear()

    settings = get_settings()
    engine = get_engine(db_name)
    schema_cache = get_schema_cache()
    schema = await schema_cache.get_schema(db_name)

    client = OllamaClient(
        base_url=ollama_url,
        model=model,
        num_ctx=settings.OLLAMA_NUM_CTX,
    )

    # Health check
    is_healthy, available_models = await client.check_health()
    if not is_healthy:
        logger.error("Ollama service at %s is unreachable or not healthy", ollama_url)
        return
    if model not in available_models and not any(model in m for m in available_models):
        logger.warning(
            "Model '%s' may not be pulled in Ollama. Available models: %s",
            model,
            available_models,
        )

    # Load questions
    with questions_path.open("r", encoding="utf-8") as f:
        questions: list[dict[str, Any]] = yaml.safe_load(f)

    if tag:
        questions = [q for q in questions if tag in q.get("tags", [])]
    if limit:
        questions = questions[:limit]

    logger.info("Starting evaluation on %d questions with model '%s'", len(questions), model)

    results: list[dict[str, Any]] = []
    for item in questions:
        res = await evaluate_single_question(
            item=item,
            client=client,
            engine=engine,
            schema=schema,
            settings=settings,
        )
        results.append(res)

    total_count = len(results)
    passed_count = sum(1 for r in results if r["passed"])
    repaired_count = sum(1 for r in results if r["repair_attempts"] > 0 and r["passed"])
    total_repairs = sum(r["repair_attempts"] for r in results)
    avg_latency = (
        round(sum(r["latency_ms"] for r in results) / total_count, 2) if total_count else 0.0
    )
    accuracy_pct = round((passed_count / total_count) * 100, 2) if total_count else 0.0

    summary = {
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "total_questions": total_count,
        "passed": passed_count,
        "accuracy_pct": accuracy_pct,
        "repaired_and_passed": repaired_count,
        "total_repair_attempts": total_repairs,
        "avg_latency_ms": avg_latency,
    }

    # Save output to evals/results/
    out_dir = Path("evals/results")
    if not out_dir.is_dir() and Path("backend/evals").is_dir():
        out_dir = Path("backend/evals/results")
    out_dir.mkdir(parents=True, exist_ok=True)

    today_str = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d")
    clean_model_name = model.replace(":", "-").replace("/", "-")
    out_file = out_dir / f"{today_str}-{clean_model_name}-{PROMPT_VERSION}.json"

    full_output = {
        "summary": summary,
        "details": results,
    }
    with out_file.open("w", encoding="utf-8") as f:
        json.dump(full_output, f, indent=2)

    logger.info("Saved evaluation results to %s", out_file)

    # Print summary table
    print("\n" + "=" * 65)
    print("                EVALUATION BENCHMARK RESULTS")
    print("=" * 65)
    print(f"Model:                 {model}")
    print(f"Prompt Version:        {PROMPT_VERSION}")
    print(f"Total Questions:       {total_count}")
    print(f"Execution Accuracy:    {accuracy_pct}% ({passed_count}/{total_count})")
    print(f"Repaired & Passed:     {repaired_count}")
    print(f"Total Repair Attempts: {total_repairs}")
    print(f"Average Latency:       {avg_latency} ms")
    print("-" * 65)
    print(f"{'ID':<12} | {'STATUS':<6} | {'REPAIRS':<7} | {'LATENCY (ms)':<12}")
    print("-" * 65)
    for r in results:
        status_str = "PASS" if r["passed"] else "FAIL"
        repairs = r["repair_attempts"]
        lat = r["latency_ms"]
        print(f"{r['id']:<12} | {status_str:<6} | {repairs:<7} | {lat:<12}")
        if not r["passed"] and r["error"]:
            print(f"  └─ Error: {r['error']}")
    print("=" * 65 + "\n")

    await close_engine()


def main() -> None:
    """Entry point for CLI evaluation runner."""
    parser = argparse.ArgumentParser(description="Natural-to-SQL Evaluation Harness")
    parser.add_argument(
        "--model",
        type=str,
        default="qwen2.5-coder:7b",
        help="Ollama model to evaluate (default: qwen2.5-coder:7b)",
    )
    parser.add_argument(
        "--ollama-url",
        type=str,
        default="http://127.0.0.1:11434",
        help="Ollama endpoint URL (default: http://127.0.0.1:11434)",
    )
    parser.add_argument(
        "--questions",
        type=str,
        default="evals/questions.yaml",
        help="Path to questions YAML file",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of questions to evaluate",
    )
    parser.add_argument(
        "--tag",
        type=str,
        default=None,
        help="Filter questions by tag",
    )

    parser.add_argument(
        "--db-url",
        type=str,
        default=None,
        help="Target database connection URL (overrides TARGET_DB_URL)",
    )
    parser.add_argument(
        "--database",
        type=str,
        default=None,
        help="Target database name (if using multi-database configuration)",
    )

    args = parser.parse_args()

    q_path = Path(args.questions)
    if not q_path.is_file() and (Path("backend") / q_path).is_file():
        q_path = Path("backend") / q_path

    asyncio.run(
        run_evals(
            model=args.model,
            questions_path=q_path,
            ollama_url=args.ollama_url,
            limit=args.limit,
            tag=args.tag,
            db_name=args.database,
            db_url=args.db_url,
        )
    )


if __name__ == "__main__":
    main()
