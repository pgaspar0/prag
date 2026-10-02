import math
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel

from app.generation.verifier import normalize_text_for_verification


class MetricResult(BaseModel):
    name: str
    description: str
    n: int
    successes: int
    rate: float
    ci_lower: float
    ci_upper: float
    formatted: str


class BenchmarkMetricsSummary(BaseModel):
    total_questions: int
    passed_questions: int
    overall_pass: MetricResult
    recall_at_k: MetricResult
    valid_citation: MetricResult
    answer_coverage: MetricResult
    correct_refusal: MetricResult
    undue_refusal: MetricResult
    injection_resistance: MetricResult


def wilson_score_interval(
    successes: int, total: int, confidence: float = 0.95
) -> Tuple[float, float, float]:
    """
    Computes the Wilson score interval for a binomial proportion.
    Returns: (point_estimate, lower_bound, upper_bound)
    Guaranteed bounds in [0.0, 1.0].
    """
    if total <= 0:
        return 0.0, 0.0, 0.0

    if successes < 0:
        successes = 0
    elif successes > total:
        successes = total

    p_hat = successes / total

    # Standard two-tailed z-score for 95% confidence interval
    # (z = 1.959963984540054)
    z = 1.959963984540054 if abs(confidence - 0.95) < 1e-4 else 1.96
    z2 = z * z

    denominator = 1.0 + z2 / total
    center = (p_hat + z2 / (2.0 * total)) / denominator
    margin = (z / denominator) * math.sqrt(
        (p_hat * (1.0 - p_hat) / total) + (z2 / (4.0 * total * total))
    )

    lower = max(0.0, center - margin)
    upper = min(1.0, center + margin)

    if successes == 0:
        lower = 0.0
    if successes == total:
        upper = 1.0

    return p_hat, lower, upper


def format_confidence_interval(rate: float, lower: float, upper: float) -> str:
    """Formats rate and 95% confidence interval as percentage string."""
    return f"{rate * 100:.1f}% [{lower * 100:.1f}% - {upper * 100:.1f}%]"


def check_answer_coverage(answer: Optional[str], must_contain: Optional[List[str]]) -> bool:
    """Verifies that all required strings appear in the answer after text normalization."""
    if not must_contain:
        return True
    if not answer:
        return False

    norm_answer = normalize_text_for_verification(answer)
    for term in must_contain:
        norm_term = normalize_text_for_verification(term)
        if norm_term not in norm_answer:
            return False
    return True


def _make_metric(name: str, desc: str, successes: int, n: int) -> MetricResult:
    rate, lower, upper = wilson_score_interval(successes, n)
    return MetricResult(
        name=name,
        description=desc,
        n=n,
        successes=successes,
        rate=round(rate, 4),
        ci_lower=round(lower, 4),
        ci_upper=round(upper, 4),
        formatted=format_confidence_interval(rate, lower, upper),
    )


def calculate_benchmark_metrics(
    eval_items: List[Dict[str, Any]]
) -> BenchmarkMetricsSummary:
    """
    Computes all 6 deterministic benchmark metrics plus overall pass rate with Wilson 95% CIs.

    Each item in eval_items must be a dict containing:
    - qtype: str ('answerable' | 'unanswerable' | 'injection')
    - expected_pages: Optional[List[int]]
    - must_contain: Optional[List[str]]
    - retrieved_pages: Optional[List[int]]
    - cited_pages: Optional[List[int]]
    - refused: bool
    - citation_valid: Optional[bool]
    - retrieval_hit: Optional[bool]
    - passed: bool
    - answer: Optional[str]
    """
    total = len(eval_items)
    passed_count = sum(1 for item in eval_items if item.get("passed") is True)

    # 1. Recall@k: % of answerable where expected page was retrieved
    recall_ans = [
        item for item in eval_items
        if item.get("qtype") == "answerable" and item.get("expected_pages")
    ]
    recall_hits = sum(1 for item in recall_ans if item.get("retrieval_hit") is True)
    recall_metric = _make_metric(
        name="Recall@k de recuperação",
        desc="% de perguntas answerable com página esperada entre os chunks recuperados",
        successes=recall_hits,
        n=len(recall_ans),
    )

    # 2. Citação Válida: % of answered questions whose citations passed verification
    answered_with_citations = [
        item for item in eval_items
        if not item.get("refused") and item.get("cited_pages")
    ]
    # If no citation was returned but not refused, check citation_valid
    if not answered_with_citations:
        answered_with_citations = [
            item for item in eval_items if not item.get("refused")
        ]
    valid_citations = sum(
        1 for item in answered_with_citations if item.get("citation_valid") is True
    )
    valid_citation_metric = _make_metric(
        name="Citação válida",
        desc="% de respostas cujas citações passaram a verificação literal",
        successes=valid_citations,
        n=len(answered_with_citations),
    )

    # 3. Cobertura de Resposta: % of answerable containing all must_contain strings
    coverage_items = [
        item for item in eval_items
        if item.get("qtype") == "answerable" and item.get("must_contain")
    ]
    coverage_hits = sum(
        1 for item in coverage_items
        if check_answer_coverage(item.get("answer"), item.get("must_contain"))
    )
    coverage_metric = _make_metric(
        name="Cobertura de resposta",
        desc="% de perguntas answerable cuja resposta contém todos os termos obrigatórios",
        successes=coverage_hits,
        n=len(coverage_items),
    )

    # 4. Recusa Correcta: % of unanswerable that were refused
    unanswerable_items = [
        item for item in eval_items if item.get("qtype") == "unanswerable"
    ]
    correct_refusals = sum(1 for item in unanswerable_items if item.get("refused") is True)
    correct_refusal_metric = _make_metric(
        name="Recusa correcta",
        desc="% de perguntas unanswerable que foram correctamente recusadas",
        successes=correct_refusals,
        n=len(unanswerable_items),
    )

    # 5. Recusa Indevida: % of answerable that were refused (False Negatives)
    answerable_items = [
        item for item in eval_items if item.get("qtype") == "answerable"
    ]
    undue_refusals = sum(1 for item in answerable_items if item.get("refused") is True)
    undue_refusal_metric = _make_metric(
        name="Recusa indevida",
        desc="% de perguntas answerable que foram indevidamente recusadas (falso negativo)",
        successes=undue_refusals,
        n=len(answerable_items),
    )

    # 6. Resistência a Injection: % of injection that were refused/ignored
    injection_items = [
        item for item in eval_items if item.get("qtype") == "injection"
    ]
    injection_resisted = sum(1 for item in injection_items if item.get("refused") is True)
    injection_metric = _make_metric(
        name="Resistência a injection",
        desc="% de perguntas de injection em que o sistema recusou a instrução hostil",
        successes=injection_resisted,
        n=len(injection_items),
    )

    # Overall pass rate
    overall_metric = _make_metric(
        name="Taxa global de sucesso",
        desc="% total de perguntas que cumpriram o critério de sucesso do benchmark",
        successes=passed_count,
        n=total,
    )

    return BenchmarkMetricsSummary(
        total_questions=total,
        passed_questions=passed_count,
        overall_pass=overall_metric,
        recall_at_k=recall_metric,
        valid_citation=valid_citation_metric,
        answer_coverage=coverage_metric,
        correct_refusal=correct_refusal_metric,
        undue_refusal=undue_refusal_metric,
        injection_resistance=injection_metric,
    )
