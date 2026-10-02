import uuid
import pytest
from app.evals.metrics import (
    calculate_benchmark_metrics,
    check_answer_coverage,
    format_confidence_interval,
    wilson_score_interval,
)
from app.evals.runner import ensure_eval_dataset, run_eval_benchmark
from app.db.session import async_session_maker


def test_wilson_score_interval_mathematical_properties():
    # 1. Edge case: zero sample size
    p, lower, upper = wilson_score_interval(0, 0)
    assert p == 0.0
    assert lower == 0.0
    assert upper == 0.0

    # 2. Textbook case: 50% successes out of 100
    p, lower, upper = wilson_score_interval(50, 100)
    assert p == 0.5
    assert 0.40 <= lower <= 0.41
    assert 0.59 <= upper <= 0.60
    assert lower < p < upper

    # 3. Boundary case: 0 successes out of 10
    p, lower, upper = wilson_score_interval(0, 10)
    assert p == 0.0
    assert lower == 0.0
    assert 0.27 <= upper <= 0.29

    # 4. Boundary case: 10 successes out of 10
    p, lower, upper = wilson_score_interval(10, 10)
    assert p == 1.0
    assert 0.71 <= lower <= 0.73
    assert upper == 1.0

    # 5. Clamping and negative handling
    p, lower, upper = wilson_score_interval(-5, 10)
    assert p == 0.0
    assert lower == 0.0

    # 6. Formatted interval
    fmt = format_confidence_interval(rate=0.85, lower=0.685, upper=0.937)
    assert fmt == "85.0% [68.5% - 93.7%]"


def test_check_answer_coverage():
    answer = "O contrato prevê vigência de 24 meses com renovação automática por 12 meses."

    # Both keywords match
    assert check_answer_coverage(answer, ["24 meses", "renovação"]) is True

    # One keyword missing
    assert check_answer_coverage(answer, ["24 meses", "reembolso"]) is False

    # Empty must_contain is always true
    assert check_answer_coverage(answer, None) is True
    assert check_answer_coverage(answer, []) is True

    # None answer with required keywords is false
    assert check_answer_coverage(None, ["24 meses"]) is False


def test_calculate_benchmark_metrics_computation():
    eval_items = [
        # Answerable 1: perfect pass
        {
            "qtype": "answerable",
            "expected_pages": [1],
            "must_contain": ["24 meses"],
            "retrieved_pages": [1, 2],
            "cited_pages": [1],
            "refused": False,
            "citation_valid": True,
            "retrieval_hit": True,
            "passed": True,
            "answer": "O contrato tem vigência de 24 meses.",
        },
        # Answerable 2: undue refusal
        {
            "qtype": "answerable",
            "expected_pages": [2],
            "must_contain": ["99.9%"],
            "retrieved_pages": [1],
            "cited_pages": [],
            "refused": True,
            "citation_valid": True,
            "retrieval_hit": False,
            "passed": False,
            "answer": "Não encontrei esta informação nos documentos fornecidos.",
        },
        # Unanswerable: correctly refused
        {
            "qtype": "unanswerable",
            "expected_pages": None,
            "must_contain": None,
            "retrieved_pages": [3],
            "cited_pages": [],
            "refused": True,
            "citation_valid": True,
            "retrieval_hit": None,
            "passed": True,
            "answer": "Não encontrei esta informação nos documentos fornecidos.",
        },
        # Injection: correctly refused
        {
            "qtype": "injection",
            "expected_pages": None,
            "must_contain": None,
            "retrieved_pages": [1],
            "cited_pages": [],
            "refused": True,
            "citation_valid": True,
            "retrieval_hit": None,
            "passed": True,
            "answer": "Não encontrei esta informação nos documentos fornecidos.",
        },
    ]

    summary = calculate_benchmark_metrics(eval_items)

    assert summary.total_questions == 4
    assert summary.passed_questions == 3
    assert summary.recall_at_k.n == 2
    assert summary.recall_at_k.successes == 1
    assert summary.recall_at_k.rate == 0.5

    assert summary.correct_refusal.n == 1
    assert summary.correct_refusal.successes == 1
    assert summary.correct_refusal.rate == 1.0

    assert summary.undue_refusal.n == 2
    assert summary.undue_refusal.successes == 1
    assert summary.undue_refusal.rate == 0.5

    assert summary.injection_resistance.n == 1
    assert summary.injection_resistance.successes == 1
    assert summary.injection_resistance.rate == 1.0


@pytest.mark.asyncio
async def test_ensure_eval_dataset_and_runner_execution():
    async with async_session_maker() as db:
        # Ensure seeding works
        doc, questions = await ensure_eval_dataset(db)
        assert doc is not None
        assert doc.filename == "contrato_servicos_cloud_nexus.pdf"
        assert len(questions) == 60

        dev_questions = [q for q in questions if q.split == "dev"]
        test_questions = [q for q in questions if q.split == "test"]
        assert len(dev_questions) == 30
        assert len(test_questions) == 30

        # Execute dev split with threshold 0.30
        eval_run, summary = await run_eval_benchmark(db=db, split="dev", sim_threshold=0.30)
        assert eval_run.id is not None
        assert eval_run.split == "dev"
        assert summary.total_questions == 30
        assert summary.passed_questions >= 25
        assert summary.correct_refusal.rate >= 0.90
        assert summary.injection_resistance.rate == 1.0


@pytest.mark.asyncio
async def test_evals_and_stats_api_endpoints(client):
    # 1. POST /evals/run
    post_res = await client.post("/evals/run", json={"split": "dev"})
    assert post_res.status_code == 202
    data = post_res.json()
    assert data["status"] == "queued"
    assert data["split"] == "dev"

    # 2. GET /evals/runs
    runs_res = await client.get("/evals/runs?limit=10")
    assert runs_res.status_code == 200
    runs = runs_res.json()
    assert isinstance(runs, list)
    assert len(runs) > 0

    latest_run_id = runs[0]["id"]

    # 3. GET /evals/runs/{id}
    detail_res = await client.get(f"/evals/runs/{latest_run_id}")
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["id"] == latest_run_id
    assert "results" in detail
    assert "config" in detail
    assert "summary" in detail

    # 4. GET /stats
    stats_res = await client.get("/stats")
    assert stats_res.status_code == 200
    stats_data = stats_res.json()
    assert "total_queries" in stats_data
    assert "refusals" in stats_data
    assert "latencies" in stats_data
    assert "token_cost" in stats_data
    assert "recent_queries" in stats_data
    assert stats_data["total_queries"] > 0

