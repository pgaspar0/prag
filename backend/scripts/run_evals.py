#!/usr/bin/env python3
"""
CLI script to run PRAG evaluation benchmarks and threshold calibration.
Usage:
    python scripts/run_evals.py --split dev
    python scripts/run_evals.py --split test
    python scripts/run_evals.py --calibrate
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

# Add backend directory to sys.path so app modules import properly
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.db.session import async_session_maker
from app.evals.runner import calibrate_thresholds, run_eval_benchmark


def print_scorecard(split: str, run_id: str, config: dict, summary) -> None:
    commit = config.get("git_commit", "unknown")
    thresh = config.get("sim_threshold", 0.55)
    gen = config.get("gen_model", "gemini-2.5-flash")
    embed = f"{config.get('embed_model', 'gemini-embedding-001')} ({config.get('embed_dim', 768)}d)"

    print("=" * 84)
    print(f"  PRAG BENCHMARK SCORECARD [Split: {split} | Git Commit: {commit}]")
    print("=" * 84)
    print(f"Run ID:    {run_id}")
    print(f"Config:    THRESHOLD={thresh:.2f} | GEN_MODEL={gen} | EMBED_MODEL={embed}")
    print("-" * 84)
    print(f"{'Métrica':<30} {'n':>5} {'Sucessos':>10} {'Taxa':>10}   {'Intervalo Wilson (95%)':>24}")
    print("-" * 84)

    metrics = [
        summary.recall_at_k,
        summary.valid_citation,
        summary.answer_coverage,
        summary.correct_refusal,
        summary.undue_refusal,
        summary.injection_resistance,
    ]

    for m in metrics:
        print(f"{m.name:<30} {m.n:>5} {m.successes:>10} {m.rate*100:>9.1f}%   {m.formatted:>24}")

    print("-" * 84)
    ov = summary.overall_pass
    print(f"{ov.name:<30} {ov.n:>5} {ov.successes:>10} {ov.rate*100:>9.1f}%   {ov.formatted:>24}")
    print("=" * 84)


def print_calibration_table(results: list) -> None:
    print("=" * 84)
    print("  CALIBRAÇÃO DE THRESHOLD DE SIMILARIDADE COSSENO (SPLIT: DEV)")
    print("=" * 84)
    print(f"{'Threshold':<12} {'Recusa Correcta':>18} {'Recusa Indevida':>18} {'Taxa Global':>18} {'Status':>12}")
    print("-" * 84)

    best_thresh = None
    best_score = -1.0

    for r in results:
        # Objective function: reward correct refusal and overall pass, penalize undue refusal
        score = r["correct_refusal_rate"] + r["overall_pass_rate"] - (2.0 * r["undue_refusal_rate"])
        is_best = False
        if score > best_score:
            best_score = score
            best_thresh = r["threshold"]

    for r in results:
        is_rec = (r["threshold"] == best_thresh)
        rec_tag = "★ ÓTIMO" if is_rec else ""
        print(
            f"{r['threshold']:<12.2f} "
            f"{r['correct_refusal_ci']:>18} "
            f"{r['undue_refusal_ci']:>18} "
            f"{r['overall_pass_ci']:>18} "
            f"{rec_tag:>12}"
        )

    print("=" * 84)
    print(f"Ponto de equilíbrio recomendado: THRESHOLD = {best_thresh:.2f}")
    print("=" * 84)


async def main_async(args: argparse.Namespace) -> None:
    async with async_session_maker() as db:
        if args.calibrate:
            print(f"A calibrar thresholds [0.40 - 0.80] no split 'dev'...")
            results = await calibrate_thresholds(db=db, split="dev")
            if args.json:
                print(json.dumps(results, indent=2))
            else:
                print_calibration_table(results)
        else:
            print(f"A executar benchmark no split '{args.split}'...")
            eval_run, summary = await run_eval_benchmark(
                db=db,
                split=args.split,
                sim_threshold=args.threshold,
            )
            if args.json:
                print(json.dumps({
                    "run_id": str(eval_run.id),
                    "config": eval_run.config,
                    "summary": summary.model_dump(),
                }, indent=2))
            else:
                print_scorecard(
                    split=args.split,
                    run_id=str(eval_run.id),
                    config=eval_run.config,
                    summary=summary,
                )


def main() -> None:
    parser = argparse.ArgumentParser(description="PRAG Automated Benchmark Runner")
    parser.add_argument(
        "--split",
        type=str,
        default="dev",
        choices=["dev", "test"],
        help="Dataset split to evaluate (default: dev)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Override similarity threshold (e.g. 0.55)",
    )
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="Run threshold calibration curve on dev split",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON format",
    )
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
