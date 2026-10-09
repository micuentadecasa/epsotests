"""Shared sanitization for API and static learner question payloads."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


def public_option(option: Mapping[str, Any]) -> dict[str, Any]:
    """Remove generator review metadata from an answer option."""

    result = dict(option)
    for key in (
        "mutation",
        "claimId",
        "claimType",
        "evaluationStatus",
        "evidence",
        "distractorRationale",
    ):
        result.pop(key, None)
    return result


def public_question(
    question: Mapping[str, Any], token: str | None = None
) -> dict[str, Any]:
    """Build the learner-facing payload without exposing the solution."""

    public = deepcopy(dict(question))
    for key in (
        "correctOption",
        "explanation",
        "explanationFragments",
        "answerEvaluation",
        "explanationDetails",
        "claims",
        "evidenceSpans",
    ):
        public.pop(key, None)
    public["options"] = [public_option(option) for option in public.get("options", ())]

    # The source passage/table/chart remains available as stimulus data, but
    # evidence annotations and the answer-bearing metadata do not.
    if isinstance(public.get("stimulus"), dict):
        public["stimulus"].pop("evidenceSpans", None)
        if isinstance(public["stimulus"].get("passage"), dict):
            public["stimulus"]["passage"].pop("evidenceSpans", None)
    public["metadata"] = {
        key: public.get("metadata", {}).get(key)
        for key in (
            "seed",
            "examProfile",
            "optionCount",
            "operation",
            "questionType",
            # Opaque variation signatures let the browser audit that a new
            # item changed its method without exposing its answer or rule.
            "methodSignature",
            "operationSignature",
            "ruleSignature",
            "evidenceSignature",
            "explanationSignature",
            "calculationSignature",
            "answerValueSignature",
        )
        if key in public.get("metadata", {})
    }
    action = public.get("actions", {}).get("explainLogic")
    if isinstance(action, dict):
        action.pop("result", None)
        action["solutionView"] = {
            "initiallyVisible": False,
            "hideAction": action.get("solutionView", {}).get("hideAction", {}),
        }
    if token is not None:
        public["solutionToken"] = token
    return public


def static_solution(question: Mapping[str, Any]) -> dict[str, Any]:
    """Return the review payload stored beside a static public question."""

    result = deepcopy(question["actions"]["explainLogic"]["result"])
    result["selectedOption"] = None
    result["isCorrect"] = None
    result["selectedReason"] = (
        "Solution preference is enabled. Select an answer to check your response."
    )
    return result
