"""
Gate 2 Backtest Engine -- validates pipeline accuracy against historical decisions.

Runs all historical sponsorships through the pipeline (eligibility + evaluation +
recommendation) and compares pipeline output to the actual historical decision.

Agreement rate >= 75% required to unlock Phase 2 / Mode A autopilot.

Usage:
    python -m app.validation.backtest --output reports/gate2_report.json
    python -m app.validation.backtest --limit 50 --verbose
"""

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------
# Decision mapping: normalize historical decisions to pipeline vocab
# ----------------------------------------------------------------

HISTORICAL_TO_PIPELINE = {
    # Approved variants
    "approved":              "APPROVE",
    "approve":               "APPROVE",
    "APPROVED":              "APPROVE",
    "vollfoerderung":        "APPROVE",
    "genehmigt":             "APPROVE",
    # Partial variants
    "partial":               "PARTIAL",
    "PARTIAL":               "PARTIAL",
    "teilfoerderung":        "PARTIAL",
    "teilgenehmigt":         "PARTIAL",
    "counter_offer":         "PARTIAL",
    # Rejected variants
    "rejected":              "REJECT",
    "reject":                "REJECT",
    "REJECTED":              "REJECT",
    "abgelehnt":             "REJECT",
    "abgelehnung":           "REJECT",
}


def normalize_decision(raw: str | None) -> str | None:
    if not raw:
        return None
    return HISTORICAL_TO_PIPELINE.get(raw.strip(), raw.upper())


# ----------------------------------------------------------------
# Result data classes
# ----------------------------------------------------------------

@dataclass
class CaseResult:
    historical_id: str
    organization_name: str
    purpose_category: str
    amount_requested: float
    amount_approved: float
    year: int
    # Ground truth
    actual_decision: str          # APPROVE / PARTIAL / REJECT
    # Pipeline output
    pipeline_decision: str | None = None
    pipeline_confidence: float = 0.0
    pipeline_score: float = 0.0
    pipeline_amount: float | None = None
    # Agreement
    agrees: bool = False
    near_miss: bool = False       # pipeline said PARTIAL, actual was APPROVE (or vice versa)
    error: str | None = None
    duration_ms: float = 0.0

    @property
    def agreement_type(self) -> Literal["exact", "near_miss", "disagree", "error"]:
        if self.error:
            return "error"
        if self.agrees:
            return "exact"
        if self.near_miss:
            return "near_miss"
        return "disagree"


@dataclass
class BacktestReport:
    run_at: str = ""
    total_cases: int = 0
    evaluated: int = 0
    errors: int = 0
    exact_agreements: int = 0
    near_misses: int = 0
    disagreements: int = 0
    agreement_rate: float = 0.0           # exact / evaluated
    adjusted_agreement_rate: float = 0.0  # (exact + near_miss*0.5) / evaluated
    gate2_passed: bool = False
    gate2_threshold: float = 0.75
    # Breakdown by category
    by_category: dict = field(default_factory=dict)
    # Breakdown by decision type
    by_actual_decision: dict = field(default_factory=dict)
    # Individual case results
    cases: list[CaseResult] = field(default_factory=list)
    # Disagreement analysis
    confusion_matrix: dict = field(default_factory=dict)


# ----------------------------------------------------------------
# Backtest Engine
# ----------------------------------------------------------------

class BacktestEngine:
    """
    Runs historical sponsorship records through the pipeline agents
    and measures agreement with actual historical decisions.
    """

    def __init__(self, config, db, verbose: bool = False):
        self.config = config
        self.db = db
        self.verbose = verbose

    async def run(
        self,
        limit: int | None = None,
        year: int | None = None,
        category: str | None = None,
    ) -> BacktestReport:
        """
        Run backtest against historical sponsorships.

        Args:
            limit: Max number of cases to evaluate (None = all)
            year: Filter by year
            category: Filter by purpose_category
        """
        report = BacktestReport(run_at=datetime.now(timezone.utc).isoformat())

        # Fetch historical records with known outcomes
        records = await self._fetch_historical(limit=limit, year=year, category=category)
        report.total_cases = len(records)
        logger.info("Backtest: loaded %d historical cases", report.total_cases)

        if not records:
            logger.warning("No historical records found -- nothing to backtest")
            return report

        # Evaluate each case
        from app.agents.eligibility import EligibilityAgent
        from app.agents.evaluation import EvaluationAgent
        from app.agents.recommendation import RecommendationAgent

        eligibility_agent = EligibilityAgent(config=self.config, db=self.db)
        evaluation_agent = EvaluationAgent(config=self.config, db=self.db)
        recommendation_agent = RecommendationAgent(config=self.config, db=self.db)

        for i, record in enumerate(records):
            case = await self._evaluate_case(
                record, eligibility_agent, evaluation_agent, recommendation_agent, i
            )
            report.cases.append(case)

            if self.verbose:
                status = "[OK]" if case.agrees else "[NEAR]" if case.near_miss else "[FAIL]"
                if case.error:
                    status = "[ERR]"
                logger.info(
                    "%s [%d/%d] %s | actual=%s pipeline=%s score=%.2f",
                    status, i + 1, report.total_cases,
                    record.get("organization_name", "?")[:30],
                    case.actual_decision, case.pipeline_decision, case.pipeline_score,
                )

        # Compute report stats
        self._compute_stats(report)
        return report

    async def _fetch_historical(
        self,
        limit: int | None,
        year: int | None,
        category: str | None,
    ) -> list[dict]:
        """Fetch historical records that have a known outcome (amount_approved is set)."""
        conditions = [
            "amount_approved IS NOT NULL",
            "amount_approved >= 0",  # 0 = rejected
        ]
        params = []
        idx = 1

        if year:
            conditions.append(f"year = ${idx}")
            params.append(year)
            idx += 1

        if category:
            conditions.append(f"purpose_category = ${idx}")
            params.append(category)
            idx += 1

        where = " AND ".join(conditions)
        query = f"""
            SELECT id, organization_name, organization_type, purpose,
                   purpose_category, region, amount_requested, amount_approved,
                   year, event_date, outcome_rating, notes
            FROM historical_sponsorships
            WHERE {where}
            ORDER BY year DESC, id
        """
        if limit:
            query += f" LIMIT ${idx}"
            params.append(limit)

        async with self.db.acquire() as conn:
            rows = await conn.fetch(query, *params)

        return [dict(r) for r in rows]

    async def _evaluate_case(
        self,
        record: dict,
        eligibility_agent,
        evaluation_agent,
        recommendation_agent,
        index: int,
    ) -> CaseResult:
        """Run one historical case through pipeline agents and compare."""
        historical_id = str(record.get("id", ""))
        org_name = record.get("organization_name", "Unknown")
        amount_approved = float(record.get("amount_approved") or 0)
        amount_requested = float(record.get("amount_requested") or amount_approved)

        # Determine ground truth decision
        if amount_approved <= 0:
            actual_decision = "REJECT"
        elif amount_approved < amount_requested * 0.95:
            actual_decision = "PARTIAL"
        else:
            actual_decision = "APPROVE"

        case = CaseResult(
            historical_id=historical_id,
            organization_name=org_name,
            purpose_category=record.get("purpose_category", "unknown"),
            amount_requested=amount_requested,
            amount_approved=amount_approved,
            year=record.get("year", 0),
            actual_decision=actual_decision,
        )

        try:
            t0 = datetime.now(timezone.utc)

            # Build synthetic extracted_data from historical record
            extracted_data = {
                "organization_name": org_name,
                "organization_type": record.get("organization_type", "unknown"),
                "purpose": record.get("purpose", ""),
                "purpose_category": record.get("purpose_category", "unknown"),
                "region": record.get("region", ""),
                "requested_amount": amount_requested,
                "event_date": str(record.get("event_date") or ""),
                "description": record.get("purpose", ""),
                "contact_name": org_name,
                "contact_email": "",
            }

            # Use a synthetic request_id (not persisted to DB)
            synthetic_id = f"backtest_{index}_{historical_id[:8]}"

            # --- Eligibility check (in-memory, no DB write) ---
            eligibility = await eligibility_agent.check(
                request_id=synthetic_id,
                extracted_data=extracted_data,
                completeness_score=0.8,
                quality_level="medium",
                missing_fields=[],
                _persist=False,
            )

            if not eligibility.eligible:
                case.pipeline_decision = "REJECT"
                case.pipeline_confidence = eligibility.confidence
                case.pipeline_score = 0.0
            else:
                # --- Evaluation (in-memory) ---
                evaluation = await evaluation_agent.evaluate(
                    request_id=synthetic_id,
                    extracted_data=extracted_data,
                    eligibility_warnings=eligibility.warnings,
                )
                case.pipeline_score = evaluation.overall_score

                # --- Recommendation (in-memory) ---
                eval_dict = {
                    "overall_score": evaluation.overall_score,
                    "strategic_fit_score": evaluation.strategic_fit_score,
                    "community_impact_score": evaluation.community_impact_score,
                    "visibility_value_score": evaluation.visibility_value_score,
                    "cost_effectiveness_score": evaluation.cost_effectiveness_score,
                    "strengths": evaluation.strengths,
                    "weaknesses": evaluation.weaknesses,
                }
                recommendation = await recommendation_agent.recommend(
                    request_id=synthetic_id,
                    extracted_data=extracted_data,
                    evaluation_scores=eval_dict,
                    benchmark_comparisons=evaluation.benchmark_comparisons,
                )
                case.pipeline_decision = recommendation.action
                case.pipeline_confidence = recommendation.confidence
                case.pipeline_amount = recommendation.recommended_amount

            case.duration_ms = (
                datetime.now(timezone.utc) - t0
            ).total_seconds() * 1000

            # Determine agreement
            case.agrees = case.pipeline_decision == actual_decision

            # Near miss: APPROVE vs PARTIAL (both are positive outcomes)
            near_miss_pairs = {("APPROVE", "PARTIAL"), ("PARTIAL", "APPROVE")}
            case.near_miss = (
                not case.agrees
                and (case.pipeline_decision, actual_decision) in near_miss_pairs
            )

        except Exception as e:
            logger.exception("Backtest case %s failed: %s", historical_id, e)
            case.error = str(e)

        return case

    def _compute_stats(self, report: BacktestReport):
        """Compute aggregate statistics from individual case results."""
        evaluated = [c for c in report.cases if not c.error]
        report.evaluated = len(evaluated)
        report.errors = len(report.cases) - report.evaluated

        report.exact_agreements = sum(1 for c in evaluated if c.agrees)
        report.near_misses = sum(1 for c in evaluated if c.near_miss)
        report.disagreements = report.evaluated - report.exact_agreements - report.near_misses

        if report.evaluated > 0:
            report.agreement_rate = report.exact_agreements / report.evaluated
            report.adjusted_agreement_rate = (
                report.exact_agreements + report.near_misses * 0.5
            ) / report.evaluated

        report.gate2_passed = report.agreement_rate >= report.gate2_threshold

        # By category
        from collections import defaultdict
        cat_stats = defaultdict(lambda: {"total": 0, "agree": 0, "near_miss": 0})
        for c in evaluated:
            cat = c.purpose_category or "unknown"
            cat_stats[cat]["total"] += 1
            if c.agrees:
                cat_stats[cat]["agree"] += 1
            elif c.near_miss:
                cat_stats[cat]["near_miss"] += 1
        report.by_category = {
            k: {**v, "rate": v["agree"] / v["total"] if v["total"] else 0}
            for k, v in cat_stats.items()
        }

        # By actual decision
        dec_stats = defaultdict(lambda: {"total": 0, "agree": 0})
        for c in evaluated:
            dec_stats[c.actual_decision]["total"] += 1
            if c.agrees:
                dec_stats[c.actual_decision]["agree"] += 1
        report.by_actual_decision = {
            k: {**v, "rate": v["agree"] / v["total"] if v["total"] else 0}
            for k, v in dec_stats.items()
        }

        # Confusion matrix: actual -> pipeline
        cm = defaultdict(lambda: defaultdict(int))
        for c in evaluated:
            actual = c.actual_decision
            predicted = c.pipeline_decision or "ERROR"
            cm[actual][predicted] += 1
        report.confusion_matrix = {k: dict(v) for k, v in cm.items()}


# ----------------------------------------------------------------
# DB persistence for Gate 2 results
# ----------------------------------------------------------------

async def save_gate2_report(db, report: BacktestReport):
    """Persist Gate 2 report summary to DB."""
    async with db.acquire() as conn:
        await conn.execute("""
            INSERT INTO gate2_results (
                run_at, total_cases, evaluated, errors,
                exact_agreements, near_misses, disagreements,
                agreement_rate, adjusted_agreement_rate,
                gate2_passed, gate2_threshold, report_json
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
        """,
            datetime.fromisoformat(report.run_at),
            report.total_cases, report.evaluated, report.errors,
            report.exact_agreements, report.near_misses, report.disagreements,
            report.agreement_rate, report.adjusted_agreement_rate,
            report.gate2_passed, report.gate2_threshold,
            json.dumps(asdict(report), default=str),
        )
    logger.info(
        "Gate 2 report saved: agreement=%.1f%%, passed=%s",
        report.agreement_rate * 100, report.gate2_passed,
    )


# ----------------------------------------------------------------
# CLI entrypoint
# ----------------------------------------------------------------

async def main():
    parser = argparse.ArgumentParser(description="Gate 2 Backtest Engine")
    parser.add_argument("--limit", type=int, default=None, help="Max cases to evaluate")
    parser.add_argument("--year", type=int, default=None, help="Filter by year")
    parser.add_argument("--category", type=str, default=None, help="Filter by category")
    parser.add_argument("--output", type=str, default="reports/gate2_report.json", help="Output file")
    parser.add_argument("--verbose", action="store_true", help="Log each case result")
    parser.add_argument("--save-db", action="store_true", help="Persist results to database")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    from app.config import get_config
    from app.persistence.database import Database

    config = get_config()
    db = Database(url=config.database.url)
    await db.connect()
    await db.init_schema()

    engine = BacktestEngine(config=config, db=db, verbose=args.verbose)
    report = await engine.run(limit=args.limit, year=args.year, category=args.category)

    # Print summary
    print("\n" + "=" * 60)
    print("GATE 2 BACKTEST REPORT")
    print("=" * 60)
    print(f"Total cases:       {report.total_cases}")
    print(f"Evaluated:         {report.evaluated}")
    print(f"Errors:            {report.errors}")
    print(f"Exact agreements:  {report.exact_agreements} ({report.agreement_rate:.1%})")
    print(f"Near misses:       {report.near_misses}")
    print(f"Disagreements:     {report.disagreements}")
    print(f"Adj. agreement:    {report.adjusted_agreement_rate:.1%}")
    print(f"Gate 2 threshold:  {report.gate2_threshold:.0%}")
    print(f"GATE 2:            {'PASSED' if report.gate2_passed else 'FAILED'}")
    print("\nBy category:")
    for cat, stats in sorted(report.by_category.items()):
        print(f"  {cat:<25} {stats['agree']}/{stats['total']} ({stats['rate']:.0%})")
    print("\nConfusion matrix (actual -> predicted):")
    for actual, preds in sorted(report.confusion_matrix.items()):
        for pred, count in sorted(preds.items()):
            marker = "OK" if actual == pred else "  "
            print(f"  {marker} actual={actual:<8} predicted={pred:<8} count={count}")
    print("=" * 60 + "\n")

    # Save JSON report
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(asdict(report), f, indent=2, default=str)
    print(f"Report saved to: {output_path}")

    # Optionally save to DB
    if args.save_db:
        await save_gate2_report(db, report)

    await db.disconnect()
    sys.exit(0 if report.gate2_passed else 1)


if __name__ == "__main__":
    asyncio.run(main())
