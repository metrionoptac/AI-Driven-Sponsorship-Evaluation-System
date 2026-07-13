"""
PipelineExecutor -- orchestrates the full sponsorship evaluation pipeline.

Runs all agents in sequence, manages state transitions, and persists results.

Pipeline flow:
  RECEIVED -> PARSING -> PARSED
  -> ELIGIBILITY_CHECK -> ELIGIBLE or REJECTED
  -> EVALUATING -> EVALUATED
  -> RECOMMENDING -> RECOMMENDED
  -> AUTO_DECIDED or HUMAN_REVIEW -> DECIDED
  -> COMPLETING -> COMPLETED
"""

import logging
from dataclasses import dataclass, field

from app.config import AppConfig
from app.pipeline.states import PipelineState
from app.agents.eligibility import EligibilityAgent, EligibilityResult
from app.agents.evaluation import EvaluationAgent, EvaluationResult
from app.agents.recommendation import RecommendationAgent, RecommendationResult
from app.agents.decision import DecisionAgent, DecisionResult
from app.agents.completion import CompletionAgent, CompletionResult
from app.agents.research import ResearchAgent, VerificationReport

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Full result of the pipeline execution."""
    request_id: str
    final_state: str = "failed"
    decision: str | None = None
    decided_amount: float | None = None
    letter_generated: bool = False
    steps_completed: list[str] = field(default_factory=list)
    error: str | None = None

    # Agent results
    eligibility: EligibilityResult | None = None
    research: VerificationReport | None = None
    evaluation: EvaluationResult | None = None
    recommendation: RecommendationResult | None = None
    decision_result: DecisionResult | None = None
    completion: CompletionResult | None = None


class PipelineExecutor:
    """Orchestrates the full pipeline from PARSED to COMPLETED."""

    def __init__(self, config: AppConfig, db=None, email_sender=None):
        self.config = config
        self.db = db
        self._email_sender = email_sender
        self.eligibility_agent = EligibilityAgent(config=config, db=db)
        self.research_agent = ResearchAgent(config=config, db=db)
        self.evaluation_agent = EvaluationAgent(config=config, db=db)
        self.recommendation_agent = RecommendationAgent(config=config, db=db)
        self.decision_agent = DecisionAgent(config=config, db=db)
        self.completion_agent = CompletionAgent(config=config, db=db)

    async def run(
        self,
        request_id: str,
        extracted_data: dict,
        completeness_score: float = 0.0,
        quality_level: str = "medium",
        missing_fields: list[str] | None = None,
        pipeline_mode: str = "copilot",
        raw_text_used: str | None = None,
    ) -> PipelineResult:
        """
        Run the full pipeline for a parsed request.

        Args:
            request_id: The request ID
            extracted_data: The SponsorshipRequest dict from Intake Agent
            completeness_score: From quality gate
            quality_level: From quality gate
            missing_fields: From quality gate
        """
        import time as _time
        result = PipelineResult(request_id=request_id)
        pipe_start = _time.time()

        try:
            # ====== ELIGIBILITY CHECK ======
            logger.info("[%s] ====== PIPELINE EXECUTOR START ======", request_id)
            logger.info("[%s] >> Stage 1/5: ELIGIBILITY CHECK", request_id)
            await self._set_state(request_id, PipelineState.ELIGIBILITY_CHECK)

            eligibility = await self.eligibility_agent.check(
                request_id=request_id,
                extracted_data=extracted_data,
                completeness_score=completeness_score,
                quality_level=quality_level,
                missing_fields=missing_fields,
            )
            result.eligibility = eligibility
            result.steps_completed.append("eligibility_check")

            # Persist eligibility result
            if self.db:
                await self.db.save_eligibility(
                    request_id=request_id,
                    eligible=eligibility.eligible,
                    rejection_type=eligibility.rejection_type,
                    rules_checked=[r.to_dict() for r in eligibility.rules_checked],
                    rejection_reasons=eligibility.rejection_reasons,
                    warnings=eligibility.warnings,
                    llm_used=eligibility.llm_used,
                    llm_assessment=eligibility.llm_assessment,
                    confidence=eligibility.confidence,
                    needs_human_review=eligibility.needs_human_review,
                )

            if not eligibility.eligible:
                # FORMAL REJECTION -- eligibility hard rule failed
                await self._set_state(request_id, PipelineState.REJECTED)
                result.decision = "REJECTED"
                result.decided_amount = 0

                # Generate formal rejection letter (standard template, factual reasons)
                await self._set_state(request_id, PipelineState.COMPLETING)
                completion = await self.completion_agent.complete(
                    request_id=request_id,
                    extracted_data=extracted_data,
                    decision={
                        "decision": "REJECTED",
                        "decided_amount": 0,
                        "rejection_type": "FORMAL",  # Tells completion agent: use standard template
                    },
                    eligibility_rejection_reasons=eligibility.rejection_reasons,
                )
                result.completion = completion
                result.letter_generated = True
                result.steps_completed.append("completion")

                if self.db:
                    await self.db.save_completion(
                        request_id=request_id,
                        letter_type="FORMAL_REJECTION",
                        letter_content=completion.letter_content,
                        letter_language=completion.letter_language,
                        sent_to=completion.sent_to,
                        template_used=completion.template_used,
                    )

                # HITL: formal rejection letter saved as draft. User sends from GUI.
                logger.info(
                    "[%s] FORMAL REJECTION letter drafted (HITL ON). Reasons: %s",
                    request_id, eligibility.rejection_reasons,
                )

                await self._set_state(request_id, PipelineState.COMPLETED)
                result.final_state = PipelineState.COMPLETED.value
                return result

            await self._set_state(request_id, PipelineState.ELIGIBLE)
            logger.info("[%s] >> Stage 1/5: ELIGIBLE (%.1fs)", request_id, _time.time() - pipe_start)

            # ====== RESEARCH + EVALUATION (PARALLEL) ======
            logger.info("[%s] >> Stage 2/5: RESEARCH + EVALUATION (parallel)", request_id)
            t_eval = _time.time()
            await self._set_state(request_id, PipelineState.EVALUATING)

            import asyncio as _asyncio

            # Run Research and Evaluation in parallel
            research_task = _asyncio.create_task(
                self.research_agent.research(
                    request_id=request_id,
                    extracted_data=extracted_data,
                    eligibility_warnings=eligibility.warnings,
                )
            )
            eval_task = _asyncio.create_task(
                self.evaluation_agent.evaluate(
                    request_id=request_id,
                    extracted_data=extracted_data,
                    eligibility_warnings=eligibility.warnings,
                    raw_text_used=raw_text_used,
                )
            )

            # Await both
            try:
                research_report = await research_task
                result.research = research_report
                result.steps_completed.append("research")
                logger.info(
                    "Research for %s: credibility=%.2f, flags=%d",
                    request_id, research_report.credibility_score,
                    len(research_report.red_flags),
                )
            except Exception as e:
                logger.warning("Research failed for %s (non-fatal): %s", request_id, e)

            evaluation = await eval_task
            result.evaluation = evaluation
            result.steps_completed.append("evaluation")

            if self.db:
                await self.db.save_evaluation(
                    request_id=request_id,
                    strategic_fit_score=evaluation.strategic_fit_score,
                    community_impact_score=evaluation.community_impact_score,
                    visibility_value_score=evaluation.visibility_value_score,
                    cost_effectiveness_score=evaluation.cost_effectiveness_score,
                    overall_score=evaluation.overall_score,
                    scoring_breakdown=evaluation.scoring_breakdown,
                    benchmark_comparisons=[
                        {"id": str(b.get("id")), "org": b.get("organization_name"),
                         "purpose": b.get("purpose"), "year": b.get("year"),
                         "amount": b.get("amount_approved"), "rating": b.get("outcome_rating")}
                        for b in evaluation.benchmark_comparisons
                    ],
                    strengths=evaluation.strengths,
                    weaknesses=evaluation.weaknesses,
                )

            await self._set_state(request_id, PipelineState.EVALUATED)
            logger.info(
                "[%s] >> Stage 2/5: EVALUATED (%.1fs) -> overall=%.2f, strategic=%.2f, "
                "community=%.2f, visibility=%.2f, cost=%.2f",
                request_id, _time.time() - t_eval,
                evaluation.overall_score, evaluation.strategic_fit_score,
                evaluation.community_impact_score, evaluation.visibility_value_score,
                evaluation.cost_effectiveness_score,
            )

            # ====== RECOMMENDATION ======
            logger.info("[%s] >> Stage 3/5: RECOMMENDATION", request_id)
            t_rec = _time.time()
            await self._set_state(request_id, PipelineState.RECOMMENDING)

            eval_dict = {
                "overall_score": evaluation.overall_score,
                "strategic_fit_score": evaluation.strategic_fit_score,
                "community_impact_score": evaluation.community_impact_score,
                "visibility_value_score": evaluation.visibility_value_score,
                "cost_effectiveness_score": evaluation.cost_effectiveness_score,
                "strengths": evaluation.strengths,
                "weaknesses": evaluation.weaknesses,
            }

            recommendation = await self.recommendation_agent.recommend(
                request_id=request_id,
                extracted_data=extracted_data,
                evaluation_scores=eval_dict,
                benchmark_comparisons=evaluation.benchmark_comparisons,
            )
            result.recommendation = recommendation
            result.steps_completed.append("recommendation")

            if self.db:
                await self.db.save_recommendation(
                    request_id=request_id,
                    action=recommendation.action,
                    recommended_amount=recommendation.recommended_amount,
                    confidence=recommendation.confidence,
                    reasoning=recommendation.reasoning,
                    conditions=recommendation.conditions,
                    similar_past_ids=recommendation.similar_past_ids,
                    risk_factors=recommendation.risk_factors,
                    auto_decidable=recommendation.auto_decidable,
                )

            await self._set_state(request_id, PipelineState.RECOMMENDED)
            logger.info(
                "[%s] >> Stage 3/5: RECOMMENDED (%.1fs) -> action=%s, amount=%s, "
                "confidence=%.2f, auto_decidable=%s",
                request_id, _time.time() - t_rec,
                recommendation.action, recommendation.recommended_amount,
                recommendation.confidence, recommendation.auto_decidable,
            )

            # ====== DECISION ======
            logger.info("[%s] >> Stage 4/5: DECISION (mode=%s)", request_id, pipeline_mode)
            rec_dict = {
                "action": recommendation.action,
                "recommended_amount": recommendation.recommended_amount,
                "confidence": recommendation.confidence,
                "auto_decidable": recommendation.auto_decidable,
                "reasoning": recommendation.reasoning,
                "conditions": recommendation.conditions,
            }

            decision_result = await self.decision_agent.decide(
                request_id=request_id,
                recommendation=rec_dict,
                pipeline_mode=pipeline_mode,
            )
            result.decision_result = decision_result
            result.decision = decision_result.decision
            result.decided_amount = decision_result.decided_amount
            result.steps_completed.append("decision")

            if decision_result.decision_mode == "AUTO":
                await self._set_state(request_id, PipelineState.AUTO_DECIDED)
            else:
                await self._set_state(request_id, PipelineState.HUMAN_REVIEW)

            if self.db:
                await self.db.save_decision(
                    request_id=request_id,
                    decision=decision_result.decision,
                    decided_amount=decision_result.decided_amount,
                    decided_by=decision_result.decided_by,
                    decision_mode=decision_result.decision_mode,
                    override_reason=decision_result.override_reason,
                    notes=decision_result.notes,
                )

            # ====== HUMAN REVIEW STOP POINT ======
            # In COPILOT mode (or when Gate 2 not passed), the pipeline STOPS here.
            # The request stays in HUMAN_REVIEW state until a human approves/rejects
            # via the Review page. The CompletionAgent runs AFTER the human decides.
            if decision_result.decision_mode != "AUTO":
                total = _time.time() - pipe_start
                result.final_state = PipelineState.HUMAN_REVIEW.value
                logger.info(
                    "[%s] ====== PIPELINE PAUSED FOR HUMAN REVIEW (%.1fs) ====== "
                    "AI recommends: %s %s EUR (confidence %.0f%%). "
                    "Waiting for human decision on Review page.",
                    request_id, total,
                    recommendation.action, recommendation.recommended_amount,
                    recommendation.confidence * 100,
                )
                return result

            # ====== AUTO-DECIDED: Continue to completion ======
            await self._set_state(request_id, PipelineState.DECIDED)
            logger.info(
                "[%s] >> Stage 4/5: AUTO-DECIDED -> %s, amount=%s",
                request_id, decision_result.decision, decision_result.decided_amount,
            )

            # ====== COMPLETION ======
            await self._complete_request(
                request_id, extracted_data, decision_result, recommendation, result,
            )

            total = _time.time() - pipe_start
            logger.info(
                "[%s] ====== PIPELINE COMPLETE (%.1fs total) ====== decision=%s, amount=%s EUR, "
                "letter=%s, steps=%s",
                request_id, total, result.decision, result.decided_amount,
                "generated" if result.letter_generated else "none",
                result.steps_completed,
            )

            return result

        except Exception as e:
            logger.exception("Pipeline failed for %s: %s", request_id, e)
            result.error = str(e)
            result.final_state = PipelineState.FAILED.value
            if self.db:
                await self._set_state(request_id, PipelineState.FAILED)
            return result

    async def complete_after_human_review(
        self,
        request_id: str,
        human_decision: str,
        human_amount: float,
        extracted_data: dict,
        recommendation_conditions: list[str] | None = None,
    ) -> PipelineResult:
        """
        Called from the Review page after a human approves/rejects/modifies.
        Generates the letter and finalizes the request.
        """
        result = PipelineResult(request_id=request_id)

        from app.agents.decision import DecisionResult
        decision_result = DecisionResult()
        decision_result.decision = human_decision
        decision_result.decided_amount = human_amount
        decision_result.decided_by = "human_reviewer"
        decision_result.decision_mode = "HUMAN"

        result.decision_result = decision_result
        result.decision = human_decision
        result.decided_amount = human_amount

        # Update the decision in DB
        if self.db:
            await self.db.save_decision(
                request_id=request_id,
                decision=human_decision,
                decided_amount=human_amount,
                decided_by="human_reviewer",
                decision_mode="HUMAN",
                override_reason=None,
                notes=f"Human reviewed and decided: {human_decision} {human_amount} EUR",
            )

        await self._set_state(request_id, PipelineState.DECIDED)
        logger.info(
            "[%s] >> HUMAN DECIDED: %s, amount=%s EUR",
            request_id, human_decision, human_amount,
        )

        # Now generate the letter
        recommendation_conditions = recommendation_conditions or []
        await self._complete_request(
            request_id, extracted_data, decision_result,
            type("Rec", (), {"conditions": recommendation_conditions})(),
            result,
        )

        logger.info(
            "[%s] ====== PIPELINE COMPLETE (after human review) ====== decision=%s, amount=%s EUR",
            request_id, human_decision, human_amount,
        )
        return result

    async def _complete_request(
        self,
        request_id: str,
        extracted_data: dict,
        decision_result,
        recommendation,
        result: PipelineResult,
    ):
        """Generate letter, update org profile, decrement budget, add to history."""
        logger.info("[%s] >> Stage 5/5: COMPLETION (letter generation)", request_id)
        await self._set_state(request_id, PipelineState.COMPLETING)

        completion = await self.completion_agent.complete(
            request_id=request_id,
            extracted_data=extracted_data,
            decision={
                "decision": decision_result.decision,
                "decided_amount": decision_result.decided_amount,
                "notes": getattr(decision_result, "notes", None),
            },
            recommendation_conditions=getattr(recommendation, "conditions", []),
        )
        result.completion = completion
        result.letter_generated = True
        result.steps_completed.append("completion")

        if self.db:
            await self.db.save_completion(
                request_id=request_id,
                letter_type=completion.letter_type,
                letter_content=completion.letter_content,
                letter_language=completion.letter_language,
                sent_to=completion.sent_to,
                template_used=completion.template_used,
            )

            # Update org profile
            org_name = extracted_data.get("organization_name")
            if org_name:
                await self.db.upsert_org_profile(
                    organization_name=org_name,
                    organization_type=extracted_data.get("organization_type"),
                    request_id=request_id,
                    approved=decision_result.decision in ("APPROVED", "PARTIAL"),
                    amount_requested=extracted_data.get("requested_amount", 0) or 0,
                    amount_given=decision_result.decided_amount or 0,
                )

            # Decrement budget if approved
            if decision_result.decision in ("APPROVED", "PARTIAL") and decision_result.decided_amount:
                await self.db.decrement_budget(decision_result.decided_amount)

            # Add to historical sponsorships
            if decision_result.decision in ("APPROVED", "PARTIAL"):
                await self.db.add_historical_sponsorship(
                    organization_name=org_name or "Unknown",
                    organization_type=extracted_data.get("organization_type", "unknown"),
                    purpose=extracted_data.get("purpose", ""),
                    purpose_category=extracted_data.get("purpose_category", "unknown"),
                    region=extracted_data.get("region", ""),
                    amount_requested=extracted_data.get("requested_amount", 0) or 0,
                    amount_approved=decision_result.decided_amount or 0,
                    year=2026,
                    event_date=extracted_data.get("event_date"),
                    request_id=request_id,
                )

        # Send decision email to sender (and CC contact if different)
        source_email = extracted_data.get("_source_email", "")
        contact = extracted_data.get("contact", {}) or {}
        contact_email = contact.get("email", "")

        # Check config: should we auto-send the letter or keep as draft for human review?
        auto_send_decision = False  # Default: HITL ON -- letter is a draft, user sends from GUI
        auto_send_rejection = False
        if self.config:
            # These would come from config/DB in production. For now, always draft.
            pass

        should_auto_send = (
            auto_send_rejection if decision_result.decision == "REJECTED" else auto_send_decision
        )

        if should_auto_send and source_email and hasattr(self, '_email_sender') and self._email_sender:
            letter_type = "APPROVAL" if decision_result.decision == "APPROVED" else (
                "PARTIAL" if decision_result.decision == "PARTIAL" else "REJECTION"
            )
            import asyncio as _asyncio
            # B49: thread the letter + real reference (same as all other senders)
            req_row = await self.db.get_request(request_id) if self.db else None
            _asyncio.create_task(
                self._email_sender.send_letter(
                    to_email=source_email,
                    request_id=request_id,
                    letter_content=completion.letter_content,
                    letter_type=letter_type,
                    original_subject=(req_row.get("source_subject")
                                      if req_row and req_row.get("received_via") == "email" else None),
                    display_id=req_row.get("display_id") if req_row else None,
                )
            )
            logger.info(
                "[%s] Decision letter auto-sent: to=%s, type=%s",
                request_id, source_email, letter_type,
            )
        else:
            logger.info(
                "[%s] Decision letter saved as DRAFT (HITL ON). User will send from GUI.",
                request_id,
            )

        await self._set_state(request_id, PipelineState.COMPLETED)
        result.final_state = PipelineState.COMPLETED.value

    async def _set_state(self, request_id: str, state: PipelineState):
        if self.db:
            await self.db.update_state(request_id, state.value, actor="pipeline_executor")
