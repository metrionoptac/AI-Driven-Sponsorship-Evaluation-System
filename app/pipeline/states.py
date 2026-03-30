"""
Pipeline state machine definitions.
Every sponsorship request moves through these states.
"""

from enum import Enum


class PipelineState(str, Enum):
    RECEIVED = "received"
    PARSING = "parsing"
    PARSED = "parsed"
    ELIGIBILITY_CHECK = "eligibility_check"
    REJECTED = "rejected"
    ELIGIBLE = "eligible"
    EVALUATING = "evaluating"
    EVALUATED = "evaluated"
    RECOMMENDING = "recommending"
    RECOMMENDED = "recommended"
    AUTO_DECIDED = "auto_decided"
    HUMAN_REVIEW = "human_review"
    DECIDED = "decided"
    COMPLETING = "completing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRY = "retry"


# Valid state transitions — enforced by DB layer
VALID_TRANSITIONS: dict[PipelineState, list[PipelineState]] = {
    PipelineState.RECEIVED: [PipelineState.PARSING, PipelineState.FAILED],
    PipelineState.PARSING: [PipelineState.PARSED, PipelineState.FAILED, PipelineState.RETRY],
    PipelineState.PARSED: [PipelineState.ELIGIBILITY_CHECK],
    PipelineState.ELIGIBILITY_CHECK: [PipelineState.REJECTED, PipelineState.ELIGIBLE, PipelineState.FAILED],
    PipelineState.REJECTED: [PipelineState.COMPLETING],
    PipelineState.ELIGIBLE: [PipelineState.EVALUATING],
    PipelineState.EVALUATING: [PipelineState.EVALUATED, PipelineState.FAILED, PipelineState.RETRY],
    PipelineState.EVALUATED: [PipelineState.RECOMMENDING],
    PipelineState.RECOMMENDING: [PipelineState.RECOMMENDED, PipelineState.FAILED],
    PipelineState.RECOMMENDED: [PipelineState.AUTO_DECIDED, PipelineState.HUMAN_REVIEW],
    PipelineState.AUTO_DECIDED: [PipelineState.DECIDED],
    PipelineState.HUMAN_REVIEW: [PipelineState.DECIDED],
    PipelineState.DECIDED: [PipelineState.COMPLETING],
    PipelineState.COMPLETING: [PipelineState.COMPLETED, PipelineState.FAILED],
    PipelineState.RETRY: [PipelineState.PARSING, PipelineState.EVALUATING],
}
