"""
Portfolio-aware scoring.

Detects category over-investment and applies score penalties to
rebalance the portfolio. Called by EvaluationAgent before finalising scores.

Rules (configurable in sponsorship_strategy.focus_areas):
  - If a category already represents > MAX_CATEGORY_SHARE of total spent,
    apply a progressive penalty to new requests in that category.
  - Portfolio balance score added as a 5th evaluation dimension.

This ensures Stadtwerke Bodensee does not over-concentrate in one area
(e.g. 80% of budget going to sports clubs).
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Maximum share of annual budget any single category should hold (default 40%)
DEFAULT_MAX_CATEGORY_SHARE = 0.40


@dataclass
class PortfolioContext:
    """Current portfolio state for a given category."""
    category: str
    total_budget: float
    spent_this_category: float
    spent_total: float
    category_share: float           # spent_this_category / spent_total (if spent_total > 0)
    budget_share: float             # spent_this_category / total_budget
    at_risk: bool                   # category_share > max_share
    penalty_factor: float           # 0.0 = no penalty, 1.0 = full penalty
    penalty_score: float            # 0.0-1.0 score to add as portfolio_balance dimension
    max_category_share: float


async def get_portfolio_context(
    db,
    category: str,
    strategy: dict | None = None,
) -> PortfolioContext:
    """
    Query DB for current portfolio state and compute penalty factor.

    Args:
        db: Database instance
        category: purpose_category of the incoming request
        strategy: Active sponsorship_strategy row (optional, fetched if None)
    """
    if strategy is None:
        strategy = await db.get_active_strategy()

    total_budget = float(strategy.get("total_budget", 150000)) if strategy else 150000.0
    remaining = float(strategy.get("remaining_budget", total_budget)) if strategy else total_budget
    spent_total = total_budget - remaining

    # Fetch spend by category from decisions table
    async with db.acquire() as conn:
        rows = await conn.fetch("""
            SELECT e.extracted_data->>'purpose_category' as cat,
                   COALESCE(SUM(d.decided_amount), 0) as total_spent
            FROM decisions d
            JOIN requests r ON r.id = d.request_id
            JOIN extraction_results e ON e.request_id = r.id
            WHERE d.decision IN ('APPROVED', 'PARTIAL')
            GROUP BY cat
        """)

    spend_by_cat = {(r["cat"] or "unknown"): float(r["total_spent"]) for r in rows}
    spent_this_category = spend_by_cat.get(category, 0.0)

    # Get max share for this category from focus_areas config
    max_share = DEFAULT_MAX_CATEGORY_SHARE
    if strategy:
        import json
        focus_areas = strategy.get("focus_areas", [])
        if isinstance(focus_areas, str):
            focus_areas = json.loads(focus_areas)
        for fa in focus_areas:
            if fa.get("category") == category:
                # Allow up to 2x the focus_area weight as max share
                max_share = min(0.70, fa.get("weight", 0.30) * 2.0)
                break

    # Calculate share
    category_share = spent_this_category / spent_total if spent_total > 0 else 0.0
    budget_share = spent_this_category / total_budget if total_budget > 0 else 0.0
    at_risk = category_share > max_share

    # Penalty factor: linear from 0 (at max_share) to 0.4 (at 2x max_share)
    if at_risk and category_share > 0:
        overshoot = (category_share - max_share) / max_share  # 0.0-1.0+
        penalty_factor = min(0.40, overshoot * 0.40)
    else:
        penalty_factor = 0.0

    # Portfolio balance score: 1.0 = healthy, reduces if at risk
    penalty_score = max(0.0, 1.0 - penalty_factor * 2.5)

    if at_risk:
        logger.info(
            "Portfolio: category '%s' at %.1f%% of spend (max %.1f%%) -- penalty %.2f",
            category, category_share * 100, max_share * 100, penalty_factor,
        )

    return PortfolioContext(
        category=category,
        total_budget=total_budget,
        spent_this_category=spent_this_category,
        spent_total=spent_total,
        category_share=category_share,
        budget_share=budget_share,
        at_risk=at_risk,
        penalty_factor=penalty_factor,
        penalty_score=penalty_score,
        max_category_share=max_share,
    )


def apply_portfolio_penalty(
    overall_score: float,
    portfolio: PortfolioContext,
) -> tuple[float, float]:
    """
    Apply portfolio penalty to overall score.

    Returns:
        (adjusted_score, portfolio_balance_score)
    """
    if not portfolio.at_risk:
        return overall_score, 1.0

    adjusted = overall_score * (1.0 - portfolio.penalty_factor)
    adjusted = max(0.0, min(1.0, adjusted))
    return adjusted, portfolio.penalty_score
