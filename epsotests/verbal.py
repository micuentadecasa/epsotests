"""Deterministic EPSO verbal-reasoning question generation.

The verbal generator keeps the reading passage, claims, evidence spans, answer
assessment, and learner explanation as separate typed models.  The resulting
JSON is self-contained: a consumer can display a passage, evaluate one answer,
or reveal the solution without re-reading or re-generating the item.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import random
from typing import Any, Mapping, Sequence

from .signatures import stable_signature
from .visual_abstract import (
    EXAM_PROFILES,
    EXPLAIN_LOGIC_ACTION_ID,
    HIDE_SOLUTION_ACTION_ID,
    ExamProfile,
    resolve_exam_profile,
)


SUPPORTED_VERBAL_QUESTION_TYPES = (
    "reading-comprehension",
    "inference",
    "true-false",
)
# ``formats`` is a useful spelling for clients that dispatch visual and verbal
# generators through one interface.
SUPPORTED_VERBAL_FORMATS = SUPPORTED_VERBAL_QUESTION_TYPES
SUPPORTED_VERBAL_DIFFICULTIES = ("easy", "medium", "hard")


@dataclass(frozen=True)
class Passage:
    """An original source passage with stable paragraph boundaries."""

    id: str
    title: str
    paragraphs: tuple[str, ...]
    source: str = "original"

    def __post_init__(self) -> None:
        paragraphs = tuple(str(paragraph).strip() for paragraph in self.paragraphs)
        if not paragraphs or any(not paragraph for paragraph in paragraphs):
            raise ValueError("a passage needs at least one non-empty paragraph")
        object.__setattr__(self, "id", str(self.id))
        object.__setattr__(self, "title", str(self.title))
        object.__setattr__(self, "paragraphs", paragraphs)
        object.__setattr__(self, "source", str(self.source))

    @property
    def text(self) -> str:
        return "\n\n".join(self.paragraphs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "text": self.text,
            "paragraphs": list(self.paragraphs),
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Passage":
        raw_paragraphs = data.get("paragraphs")
        if raw_paragraphs:
            paragraphs = tuple(str(item) for item in raw_paragraphs)
        else:
            paragraphs = tuple(str(data.get("text", "")).split("\n\n"))
        return cls(
            id=str(data.get("id", "passage")),
            title=str(data.get("title", "")),
            paragraphs=paragraphs,
            source=str(data.get("source", "original")),
        )


@dataclass(frozen=True)
class EvidenceSpan:
    """A character-addressable quotation from the source passage."""

    id: str
    start: int
    end: int
    text: str
    paragraph: int
    source: str = "passage"

    def __post_init__(self) -> None:
        start, end = int(self.start), int(self.end)
        if start < 0 or end <= start:
            raise ValueError("evidence span must have a positive range")
        if int(self.paragraph) < 1:
            raise ValueError("evidence paragraph numbers start at one")
        object.__setattr__(self, "id", str(self.id))
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        object.__setattr__(self, "text", str(self.text))
        object.__setattr__(self, "paragraph", int(self.paragraph))
        object.__setattr__(self, "source", str(self.source))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "paragraph": self.paragraph,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EvidenceSpan":
        return cls(
            id=str(data["id"]),
            start=int(data["start"]),
            end=int(data["end"]),
            text=str(data["text"]),
            paragraph=int(data.get("paragraph", 1)),
            source=str(data.get("source", "passage")),
        )


@dataclass(frozen=True)
class Claim:
    """A candidate statement and its relationship to the passage."""

    id: str
    text: str
    claim_type: str
    status: str
    evidence_ids: tuple[str, ...]
    reasoning: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", str(self.id))
        object.__setattr__(self, "text", str(self.text))
        object.__setattr__(self, "claim_type", str(self.claim_type))
        object.__setattr__(self, "status", str(self.status))
        object.__setattr__(self, "evidence_ids", tuple(str(item) for item in self.evidence_ids))
        object.__setattr__(self, "reasoning", str(self.reasoning))

    @property
    def explicit(self) -> bool:
        return self.claim_type == "explicit-fact"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "claimType": self.claim_type,
            "status": self.status,
            "evidence": list(self.evidence_ids),
            "reasoning": self.reasoning,
            "explicit": self.explicit,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Claim":
        return cls(
            id=str(data["id"]),
            text=str(data["text"]),
            claim_type=str(data.get("claimType", data.get("claim_type", "explicit-fact"))),
            status=str(data.get("status", "not-stated")),
            evidence_ids=tuple(data.get("evidence", data.get("evidenceIds", ()))),
            reasoning=str(data.get("reasoning", "")),
        )


@dataclass(frozen=True)
class AnswerEvaluation:
    """The evidence-based assessment of one answer option."""

    option_id: str
    claim_id: str
    status: str
    is_correct: bool
    evidence_ids: tuple[str, ...]
    reasoning: str
    distractor_rationale: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "option_id", str(self.option_id))
        object.__setattr__(self, "claim_id", str(self.claim_id))
        object.__setattr__(self, "status", str(self.status))
        object.__setattr__(self, "is_correct", bool(self.is_correct))
        object.__setattr__(self, "evidence_ids", tuple(str(item) for item in self.evidence_ids))
        object.__setattr__(self, "reasoning", str(self.reasoning))
        object.__setattr__(self, "distractor_rationale", str(self.distractor_rationale))

    def to_dict(self) -> dict[str, Any]:
        result = {
            "option": self.option_id,
            "optionId": self.option_id,
            "claimId": self.claim_id,
            "status": self.status,
            "verdict": "correct" if self.is_correct else "distractor",
            "isCorrect": self.is_correct,
            "evidence": list(self.evidence_ids),
            "reasoning": self.reasoning,
            "rationale": self.distractor_rationale,
        }
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AnswerEvaluation":
        return cls(
            option_id=str(data.get("option", data.get("optionId", ""))),
            claim_id=str(data.get("claimId", "")),
            status=str(data.get("status", "not-stated")),
            is_correct=bool(data.get("isCorrect", data.get("verdict") == "correct")),
            evidence_ids=tuple(data.get("evidence", data.get("evidenceIds", ()))),
            reasoning=str(data.get("reasoning", "")),
            distractor_rationale=str(data.get("rationale", data.get("distractorRationale", ""))),
        )


@dataclass(frozen=True)
class VerbalOption:
    """One learner-facing answer option."""

    id: str
    text: str
    claim_id: str
    claim_type: str
    status: str
    evidence_ids: tuple[str, ...]
    distractor_rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.text,
            "text": self.text,
            "claimId": self.claim_id,
            "claimType": self.claim_type,
            "evaluationStatus": self.status,
            "evidence": list(self.evidence_ids),
            "distractorRationale": self.distractor_rationale,
            "mutation": {
                "kind": "correct" if not self.distractor_rationale else "verbal-misreading",
                "description": self.distractor_rationale or "matches the passage and question",
            },
        }


@dataclass(frozen=True)
class VerbalExplanation:
    """A structured solution that cites evidence and separates fact from inference."""

    text: str
    reasoning_steps: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    explicit_facts: tuple[str, ...]
    invalid_inferences: tuple[str, ...]
    conclusion: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "reasoningSteps": list(self.reasoning_steps),
            "evidence": list(self.evidence_ids),
            "explicitFacts": list(self.explicit_facts),
            "invalidInferences": list(self.invalid_inferences),
            "conclusion": self.conclusion,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "VerbalExplanation":
        return cls(
            text=str(data.get("text", "")),
            reasoning_steps=tuple(data.get("reasoningSteps", ())),
            evidence_ids=tuple(data.get("evidence", data.get("evidenceIds", ()))),
            explicit_facts=tuple(data.get("explicitFacts", ())),
            invalid_inferences=tuple(data.get("invalidInferences", ())),
            conclusion=str(data.get("conclusion", "")),
        )


@dataclass(frozen=True)
class VerbalQuestion:
    """Typed view of a portable verbal learner-facing payload."""

    id: str
    item_number: int
    exam_profile: str
    option_count: int
    question_type: str
    difficulty: str
    passage: Passage
    question: str
    claims: tuple[Claim, ...]
    evidence_spans: tuple[EvidenceSpan, ...]
    options: tuple[Mapping[str, Any], ...]
    correct_option: str
    answer_evaluation: tuple[AnswerEvaluation, ...]
    explanation: VerbalExplanation
    actions: Mapping[str, Any]
    metadata: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        passage = self.passage.to_dict()
        evidence = [span.to_dict() for span in self.evidence_spans]
        claims = [claim.to_dict() for claim in self.claims]
        evaluations = [item.to_dict() for item in self.answer_evaluation]
        details = self.explanation.to_dict()
        return {
            "id": self.id,
            "itemNumber": self.item_number,
            "exam": "verbal",
            "examProfile": self.exam_profile,
            "optionCount": self.option_count,
            "format": self.question_type,
            "questionType": self.question_type,
            "difficulty": self.difficulty,
            "passage": passage,
            "sourcePassage": passage,
            "passageText": self.passage.text,
            "stimulus": {
                "type": "passage",
                "title": self.passage.title,
                "passage": passage,
                "text": self.passage.text,
                "evidenceSpans": evidence,
            },
            "question": self.question,
            "claims": claims,
            "evidenceSpans": evidence,
            "options": [dict(option) for option in self.options],
            "correctOption": self.correct_option,
            "answerEvaluation": evaluations,
            "explanation": self.explanation.text,
            "explanationDetails": details,
            "explanationFragments": list(self.explanation.reasoning_steps),
            "actions": dict(self.actions),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "VerbalQuestion":
        raw_passage = data.get("passage", data.get("sourcePassage"))
        if isinstance(raw_passage, Mapping):
            passage = Passage.from_dict(raw_passage)
        else:
            passage = Passage(
                id="passage",
                title="",
                paragraphs=tuple(str(raw_passage or "").split("\n\n")),
            )
        details = data.get("explanationDetails")
        if isinstance(details, Mapping):
            explanation = VerbalExplanation.from_dict(details)
        else:
            explanation = VerbalExplanation(
                text=str(data.get("explanation", "")),
                reasoning_steps=tuple(data.get("explanationFragments", ())),
                evidence_ids=(),
                explicit_facts=(),
                invalid_inferences=(),
                conclusion="",
            )
        return cls(
            id=str(data["id"]),
            item_number=int(data.get("itemNumber", 1)),
            exam_profile=str(data["examProfile"]),
            option_count=int(data["optionCount"]),
            question_type=str(data.get("questionType", data.get("format", "reading-comprehension"))),
            difficulty=str(data.get("difficulty", "medium")),
            passage=passage,
            question=str(data["question"]),
            claims=tuple(Claim.from_dict(item) for item in data.get("claims", ())),
            evidence_spans=tuple(EvidenceSpan.from_dict(item) for item in data.get("evidenceSpans", ())),
            options=tuple(dict(item) for item in data.get("options", ())),
            correct_option=str(data["correctOption"]),
            answer_evaluation=tuple(AnswerEvaluation.from_dict(item) for item in data.get("answerEvaluation", ())),
            explanation=explanation,
            actions=dict(data.get("actions", {})),
            metadata=dict(data.get("metadata", {})),
        )


# Descriptive aliases make the typed API easy to discover without duplicating
# the serialisation model.
VerbalPassage = Passage
VerbalClaim = Claim
VerbalEvidenceSpan = EvidenceSpan
VerbalEvidence = EvidenceSpan
VerbalAnswerEvaluation = AnswerEvaluation
Explanation = VerbalExplanation
SUPPORTED_VERBAL_TYPES = SUPPORTED_VERBAL_QUESTION_TYPES


@dataclass(frozen=True)
class _Scenario:
    id: str
    title: str
    paragraphs: tuple[str, ...]

    def passage(self) -> Passage:
        return Passage(self.id, self.title, self.paragraphs)


@dataclass(frozen=True)
class _OptionBlueprint:
    text: str
    claim_type: str
    status: str
    evidence_quotes: tuple[str, ...]
    rationale: str
    reasoning: str


def _option(
    text: str,
    claim_type: str,
    status: str,
    evidence: Sequence[str],
    rationale: str,
    reasoning: str,
) -> _OptionBlueprint:
    return _OptionBlueprint(text, claim_type, status, tuple(evidence), rationale, reasoning)


_SCENARIOS = (
    _Scenario(
        "permit-precheck",
        "A shorter visit to the permit office",
        (
            "To reduce waiting time, the North District permit office introduced an online pre-check in April. Applicants may upload forms before visiting, but an officer still verifies original identity documents at the appointment.",
            "During the first six weeks, average counter time fell from 18 minutes to 11 minutes. The office handled 14% more applications than in the same period last year.",
            "The office did not extend opening hours; it reassigned two clerks from filing to pre-checks.",
        ),
    ),
    _Scenario(
        "river-sensors",
        "What the river sensors can show",
        (
            "The regional environment agency installed sensors at three river gauges in May. Each sensor records water level every 15 minutes and sends the readings to a central dashboard.",
            "During the summer drought, the level at the Willow gauge stayed below the agency's alert threshold for nine days. Staff reviewed an alert before issuing any public bulletin.",
            "Heavy rain in September produced two alerts in three days, but neither led to a closure because the water level receded within four hours. The sensors report current levels; they do not predict rainfall.",
        ),
    ),
    _Scenario(
        "archive-maps",
        "The archive's first digitisation phase",
        (
            "The city archive prioritised maps dated before 1950 for its first digitisation phase. Each map is catalogued before scanning, and a quality check is completed before a public access copy is posted.",
            "In May, the team scanned 320 maps. Volunteers transcribed handwritten labels for 90 of those maps; the volunteers did not operate the scanners.",
            "The project creates digital access copies while the original maps remain in the archive reading room.",
        ),
    ),
    _Scenario(
        "translation-queue",
        "Managing an urgent translation queue",
        (
            "The Commission's translation unit schedules urgent requests in a shared queue. Requests marked urgent are reviewed by a coordinator before translators are assigned.",
            "In June, 42 urgent requests entered the queue; 35 were assigned within two working days. The remainder waited for a specialist language pair.",
            "The unit introduced a daily capacity cap of 18 assignments to protect quality. The cap applies to all requests, not only urgent ones.",
        ),
    ),
)


# Each set has five options, with one supported answer and four deliberately
# different distractor errors: contradiction, omitted qualifier, and invalid
# causal or generalising inferences.  Evidence quotes are exact substrings.
_BLUEPRINTS: dict[str, dict[str, tuple[str, tuple[_OptionBlueprint, ...]]]] = {
    "permit-precheck": {
        "reading-comprehension": (
            "What must applicants still do at their appointment?",
            (
                _option("Present original identity documents for verification.", "explicit-fact", "supported", ("but an officer still verifies original identity documents at the appointment.",), "matches the explicit appointment requirement", "The passage directly states this requirement."),
                _option("Upload every form at the office rather than online.", "contradicted", "contradicted", ("Applicants may upload forms before visiting",), "reverses the passage's permission to upload forms before the visit", "The passage allows online upload before the visit."),
                _option("Attend an office that has extended its opening hours.", "contradicted", "contradicted", ("The office did not extend opening hours",), "confuses the staffing change with an extension of opening hours", "The passage explicitly says opening hours did not change."),
                _option("Wait at the counter for 18 minutes on average.", "contradicted", "contradicted", ("average counter time fell from 18 minutes to 11 minutes",), "uses the earlier average as if it were the current one", "The later average is 11 minutes, not 18."),
                _option("Skip the appointment because the pre-check replaces identity checks.", "invalid-inference", "not-stated", ("Applicants may upload forms before visiting",), "treats online form upload as removal of the appointment and identity check", "The passage separates online form upload from the identity check at the appointment."),
            ),
        ),
        "inference": (
            "Which conclusion is best supported by the passage?",
            (
                _option("The office changed how existing clerical staff were allocated.", "supported-inference", "supported", ("it reassigned two clerks from filing to pre-checks",), "draws the limited staffing conclusion stated by the reassignment", "The reassignment is an explicit fact; the conclusion only restates its operational implication."),
                _option("The online pre-check eliminated the need for in-person appointments.", "invalid-inference", "not-stated", ("an officer still verifies original identity documents at the appointment",), "infers that an online step removed an appointment even though the passage says an appointment remains", "The evidence points in the opposite direction: identity is still checked at an appointment."),
                _option("Longer opening hours caused the increase in applications.", "contradicted", "contradicted", ("The office did not extend opening hours",), "assigns the result to a change the passage expressly rules out", "No extension of opening hours occurred."),
                _option("Every applicant saved exactly seven minutes.", "invalid-inference", "not-stated", ("average counter time fell from 18 minutes to 11 minutes",), "turns an average change into an identical result for every applicant", "An average does not establish the result for every individual."),
                _option("The reassigned clerks alone caused the 14% increase.", "invalid-inference", "not-stated", ("The office handled 14% more applications than in the same period last year",), "claims a sole cause that the passage does not establish", "The passage reports the increase but does not isolate one cause."),
            ),
        ),
        "true-false": (
            "Which statement is true according to the passage?",
            (
                _option("Average counter time fell by seven minutes during the first six weeks.", "explicit-fact", "supported", ("average counter time fell from 18 minutes to 11 minutes",), "correctly subtracts the two stated averages", "The stated figures give 18 minus 11, or seven minutes."),
                _option("The office extended its opening hours in April.", "contradicted", "contradicted", ("The office did not extend opening hours",), "directly contradicts the passage", "The passage explicitly says opening hours were not extended."),
                _option("Applicants may omit original identity documents after using pre-check.", "contradicted", "contradicted", ("an officer still verifies original identity documents at the appointment",), "removes a requirement that remains in force", "The identity check still occurs at the appointment."),
                _option("The office handled 14% fewer applications than last year.", "contradicted", "contradicted", ("The office handled 14% more applications than in the same period last year",), "reverses more and fewer", "The passage says applications increased by 14%."),
                _option("All counter visits now take exactly 11 minutes.", "invalid-inference", "not-stated", ("average counter time fell from 18 minutes to 11 minutes",), "treats an average as an exact duration for every visit", "The passage reports an average, not identical visit times."),
            ),
        ),
    },
    "river-sensors": {
        "reading-comprehension": (
            "How often does each sensor record the water level?",
            (
                _option("Every 15 minutes.", "explicit-fact", "supported", ("Each sensor records water level every 15 minutes",), "matches the stated recording interval", "The interval is stated directly in the first paragraph."),
                _option("Once every hour.", "contradicted", "contradicted", ("Each sensor records water level every 15 minutes",), "changes the four-times-per-hour interval to once per hour", "The passage specifies 15 minutes, not one hour."),
                _option("Only when staff issue a public bulletin.", "contradicted", "contradicted", ("sends the readings to a central dashboard",), "confuses automatic readings with the later bulletin review", "Sensors send readings to the dashboard continuously at the stated interval."),
                _option("Only during a drought.", "invalid-inference", "not-stated", ("Each sensor records water level every 15 minutes",), "limits the sensor operation to a condition the passage does not impose", "The passage gives a regular interval and does not limit it to droughts."),
                _option("They predict rainfall before it occurs.", "contradicted", "contradicted", ("The sensors report current levels; they do not predict rainfall",), "attributes a forecasting capability the passage denies", "The final sentence expressly rules out rainfall prediction."),
            ),
        ),
        "inference": (
            "Which conclusion is best supported by the passage?",
            (
                _option("An alert does not automatically result in a river closure.", "supported-inference", "supported", ("neither led to a closure because the water level receded within four hours",), "draws the reported relationship between alerts and closures", "The passage gives two alerts that did not lead to closure, so an alert alone is not an automatic closure decision."),
                _option("Every alert is ignored when water recedes within four hours.", "invalid-inference", "not-stated", ("Staff reviewed an alert before issuing any public bulletin",), "generalises from two September alerts and omits the review process", "The passage does not say alerts are ignored; staff review them."),
                _option("The sensors can predict whether rainfall will occur.", "contradicted", "contradicted", ("they do not predict rainfall",), "contradicts the stated limitation", "The sensors report current levels only."),
                _option("A public bulletin is issued before staff review an alert.", "contradicted", "contradicted", ("Staff reviewed an alert before issuing any public bulletin",), "reverses the order of review and bulletin", "The passage states that review comes first."),
                _option("The drought lasted exactly nine days across all three gauges.", "invalid-inference", "not-stated", ("the level at the Willow gauge stayed below the agency's alert threshold for nine days",), "extends one gauge's duration to every gauge and calls it the drought duration", "Only the Willow gauge and its below-threshold period are specified."),
            ),
        ),
        "true-false": (
            "Which statement is true according to the passage?",
            (
                _option("Staff review an alert before issuing a public bulletin.", "explicit-fact", "supported", ("Staff reviewed an alert before issuing any public bulletin",), "matches the stated review order", "This procedure is stated explicitly."),
                _option("The sensors predict rainfall.", "contradicted", "contradicted", ("they do not predict rainfall",), "contradicts the sensor limitation", "The passage says the sensors do not predict rainfall."),
                _option("Both September alerts caused a river closure.", "contradicted", "contradicted", ("neither led to a closure",), "reverses the outcome of both alerts", "Neither September alert led to closure."),
                _option("Sensors record readings only once a day.", "contradicted", "contradicted", ("Each sensor records water level every 15 minutes",), "changes the recording interval", "The stated interval is every 15 minutes."),
                _option("All three gauges stayed below threshold for nine days.", "invalid-inference", "not-stated", ("the level at the Willow gauge stayed below the agency's alert threshold for nine days",), "generalises the Willow result to gauges not described that way", "Only the Willow gauge is identified in that statement."),
            ),
        ),
    },
    "archive-maps": {
        "reading-comprehension": (
            "What happens before a public access copy is posted?",
            (
                _option("A quality check is completed.", "explicit-fact", "supported", ("a quality check is completed before a public access copy is posted",), "matches the stated sequence", "The passage explicitly gives the quality check as a prior step."),
                _option("Volunteers operate the scanners.", "contradicted", "contradicted", ("the volunteers did not operate the scanners",), "contradicts the volunteers' stated role", "The passage says volunteers transcribed labels, not operated scanners."),
                _option("The original map is removed from the reading room.", "contradicted", "contradicted", ("the original maps remain in the archive reading room",), "contradicts the stated location of originals", "The originals remain in the reading room."),
                _option("The map must be dated after 1950.", "contradicted", "contradicted", ("prioritised maps dated before 1950",), "reverses the archive's prioritisation", "The first phase prioritises maps before 1950."),
                _option("A volunteer transcribes every label on the map.", "invalid-inference", "not-stated", ("Volunteers transcribed handwritten labels for 90 of those maps",), "changes a stated subset into every map and every label", "The passage specifies 90 maps, not all maps."),
            ),
        ),
        "inference": (
            "Which conclusion is best supported by the passage?",
            (
                _option("The project provides digital access without requiring the original maps to leave the archive.", "supported-inference", "supported", ("creates digital access copies", "original maps remain in the archive reading room"), "combines the two explicit project outcomes", "The two cited facts support digital access while the originals stay in place."),
                _option("Volunteers completed the scanning faster than staff could.", "invalid-inference", "not-stated", ("the volunteers did not operate the scanners",), "infers a speed comparison that is not reported", "No scanning speed comparison is given."),
                _option("Every map in the archive was digitised in May.", "invalid-inference", "not-stated", ("In May, the team scanned 320 maps",), "turns a monthly count into the entire archive", "The passage gives a count, not complete coverage."),
                _option("Quality checks are unnecessary because copies are digital.", "contradicted", "contradicted", ("a quality check is completed before a public access copy is posted",), "rejects a step the project explicitly requires", "Quality checking is required before posting."),
                _option("The archive's first phase began with maps dated after 1950.", "contradicted", "contradicted", ("prioritised maps dated before 1950",), "reverses the stated priority", "The first phase prioritised maps before 1950."),
            ),
        ),
        "true-false": (
            "Which statement is true according to the passage?",
            (
                _option("Volunteers transcribed handwritten labels for 90 maps.", "explicit-fact", "supported", ("Volunteers transcribed handwritten labels for 90 of those maps",), "matches the stated volunteer activity and count", "This fact is stated directly."),
                _option("Volunteers operated the scanners.", "contradicted", "contradicted", ("the volunteers did not operate the scanners",), "contradicts the passage", "The passage explicitly excludes scanner operation from the volunteer role."),
                _option("Original maps were moved out of the reading room.", "contradicted", "contradicted", ("original maps remain in the archive reading room",), "contradicts where originals remain", "The passage says the originals remain in the reading room."),
                _option("The team scanned 3,200 maps in May.", "contradicted", "contradicted", ("the team scanned 320 maps",), "adds a zero to the reported count", "The reported count is 320."),
                _option("Every map received a volunteer transcription.", "invalid-inference", "not-stated", ("Volunteers transcribed handwritten labels for 90 of those maps",), "expands a subset to the entire project", "Only 90 maps are identified as having volunteer transcriptions."),
            ),
        ),
    },
    "translation-queue": {
        "reading-comprehension": (
            "Who reviews a request marked urgent before a translator is assigned?",
            (
                _option("A coordinator.", "explicit-fact", "supported", ("Requests marked urgent are reviewed by a coordinator before translators are assigned",), "matches the stated review process", "The passage identifies the coordinator as the reviewer."),
                _option("The translator who will do the work.", "not-stated", "not-stated", ("before translators are assigned",), "adds a role the passage does not identify as reviewer", "The passage names a coordinator, not the eventual translator."),
                _option("A specialist language-pair team in every case.", "not-stated", "not-stated", ("The remainder waited for a specialist language pair",), "treats one reason for delay as the universal reviewer", "The passage mentions specialist pairs only for the requests that waited."),
                _option("No one; urgent requests are assigned automatically.", "contradicted", "contradicted", ("are reviewed by a coordinator before translators are assigned",), "omits the explicit review step", "The passage says review occurs before assignment."),
                _option("The quality-cap committee.", "not-stated", "not-stated", ("a daily capacity cap of 18 assignments",), "introduces a committee not mentioned in the passage", "The passage describes a cap but no committee."),
            ),
        ),
        "inference": (
            "Which conclusion is best supported by the passage?",
            (
                _option("The capacity cap applies beyond urgent requests.", "supported-inference", "supported", ("The cap applies to all requests, not only urgent ones",), "restates the scope of the cap", "The final sentence explicitly supports this conclusion."),
                _option("Every urgent request is assigned within two working days.", "contradicted", "contradicted", ("35 were assigned within two working days. The remainder waited",), "ignores the requests that waited longer", "Only 35 of 42 urgent requests met that timing."),
                _option("The specialist language pair caused all queue delays.", "invalid-inference", "not-stated", ("The remainder waited for a specialist language pair",), "turns one reported delay reason into a complete causal account", "The passage does not establish that it caused all delays."),
                _option("The daily cap was designed to increase the number of assignments.", "contradicted", "contradicted", ("introduced a daily capacity cap of 18 assignments to protect quality",), "reverses the stated purpose of the cap", "The stated purpose is to protect quality."),
                _option("Urgent requests bypass coordinator review.", "contradicted", "contradicted", ("Requests marked urgent are reviewed by a coordinator before translators are assigned",), "reverses the process order", "Urgent requests are reviewed before assignment."),
            ),
        ),
        "true-false": (
            "Which statement is true according to the passage?",
            (
                _option("The daily capacity cap applies to all requests.", "explicit-fact", "supported", ("The cap applies to all requests, not only urgent ones",), "matches the stated scope", "This is an explicit fact in the final paragraph."),
                _option("All 42 urgent requests were assigned within two working days.", "contradicted", "contradicted", ("35 were assigned within two working days. The remainder waited",), "changes 35 of 42 into all 42", "The passage says the remainder waited."),
                _option("Urgent requests are assigned before coordinator review.", "contradicted", "contradicted", ("reviewed by a coordinator before translators are assigned",), "reverses the stated order", "Review comes before assignment."),
                _option("The capacity cap is 42 assignments per day.", "contradicted", "contradicted", ("a daily capacity cap of 18 assignments",), "uses the monthly urgent-request count as the daily cap", "The cap is 18 assignments per day."),
                _option("Only urgent requests are subject to the capacity cap.", "contradicted", "contradicted", ("The cap applies to all requests, not only urgent ones",), "reverses the scope of the cap", "The passage explicitly includes all requests."),
            ),
        ),
    },
}


def _difficulty_name(difficulty: str | int) -> str:
    if isinstance(difficulty, int):
        return ("easy", "medium", "hard")[max(0, min(2, difficulty - 1))]
    value = str(difficulty).strip().lower()
    if value in ("1", "easy", "low"):
        return "easy"
    if value in ("3", "hard", "high"):
        return "hard"
    if value not in SUPPORTED_VERBAL_DIFFICULTIES:
        raise ValueError(f"Unsupported verbal difficulty: {difficulty}")
    return value


def _question_type(value: str | None) -> str:
    normalized = str(value or "reading-comprehension").strip().lower().replace("_", "-")
    aliases = {
        "reading": "reading-comprehension",
        "comprehension": "reading-comprehension",
        "reading-comprehension": "reading-comprehension",
        "infer": "inference",
        "inferences": "inference",
        "truefalse": "true-false",
        "true-false": "true-false",
        "truth-evaluation": "true-false",
        "evaluation": "true-false",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in SUPPORTED_VERBAL_QUESTION_TYPES:
        available = ", ".join(SUPPORTED_VERBAL_QUESTION_TYPES)
        raise ValueError(f"Unsupported verbal question type {value!r}; use {available}")
    return normalized


def _evidence_spans(passage: Passage, quotes: Sequence[str]) -> tuple[tuple[EvidenceSpan, ...], dict[str, str]]:
    spans: list[EvidenceSpan] = []
    ids: dict[str, str] = {}
    for quote in quotes:
        quote = str(quote)
        if quote in ids:
            continue
        start = passage.text.find(quote)
        if start < 0:
            raise ValueError(f"evidence quote is not in passage {passage.id!r}: {quote!r}")
        end = start + len(quote)
        paragraph = passage.text[:start].count("\n\n") + 1
        evidence_id = f"evidence-{len(spans) + 1}"
        spans.append(EvidenceSpan(evidence_id, start, end, passage.text[start:end], paragraph))
        ids[quote] = evidence_id
    return tuple(spans), ids


def _fallback_option(index: int, passage: Passage) -> _OptionBlueprint:
    quote = passage.paragraphs[0].split(".", 1)[0] + "."
    return _option(
        f"The passage states an additional requirement numbered {index}.",
        "invalid-inference",
        "not-stated",
        (quote,),
        "adds a requirement that the passage does not state",
        "The cited sentence does not establish this additional requirement.",
    )


def _explain_action(
    explanation: VerbalExplanation,
    question_type: str,
    profile: ExamProfile,
    evaluations: Sequence[AnswerEvaluation],
    evidence: Sequence[EvidenceSpan],
    claims: Sequence[Claim],
    correct_option: str,
) -> dict[str, Any]:
    distractors = []
    for evaluation in evaluations:
        if evaluation.is_correct:
            continue
        distractors.append(
            {
                "option": evaluation.option_id,
                "reason": evaluation.distractor_rationale,
                "rationale": evaluation.distractor_rationale,
                "status": evaluation.status,
                "claimId": evaluation.claim_id,
                "evidence": list(evaluation.evidence_ids),
            }
        )
    return {
        "id": EXPLAIN_LOGIC_ACTION_ID,
        "type": "button",
        "label": "Explain logic",
        "localizedLabel": "Ver solución",
        "labels": {"en": "Explain Logic", "es": "Ver solución"},
        "ariaLabel": "Explain Logic / Ver solución",
        "initiallyVisible": False,
        "revealsAnswer": True,
        "solutionView": {
            "initiallyVisible": False,
            "hideAction": {
                "id": HIDE_SOLUTION_ACTION_ID,
                "type": "button",
                "label": "Hide solution",
                "localizedLabel": "Ocultar solución",
                "visibleAfterReveal": True,
            },
        },
        "result": {
            "optionCount": profile.option_count,
            "questionType": question_type,
            "explanation": explanation.text,
            "explanationDetails": explanation.to_dict(),
            "reasoningSteps": list(explanation.reasoning_steps),
            "evidenceSpans": [item.to_dict() for item in evidence],
            "claims": [item.to_dict() for item in claims],
            "answerEvaluation": [item.to_dict() for item in evaluations],
            "correctOption": correct_option,
            "correctReason": f"Option {correct_option} is correct because it is supported by the cited passage evidence.",
            "distractors": distractors,
        },
    }


def generate_verbal_question(
    question_type: str = "reading-comprehension",
    seed: int = 0,
    difficulty: str | int = "medium",
    exam_profile: str | ExamProfile | None = None,
    *,
    format: str | None = None,
) -> dict[str, Any]:
    """Generate one deterministic passage-based verbal reasoning question."""

    if format is not None:
        question_type = format
    normalized_type = _question_type(question_type)
    level = _difficulty_name(difficulty)
    profile = resolve_exam_profile(exam_profile)
    seed = int(seed)
    # Use an explicit stride through the scenario catalog rather than a random
    # draw: adjacent catalog seeds must exercise a different evidence path.
    scenario_index = (abs(seed) * 7 + len(normalized_type) * 3) % len(_SCENARIOS)
    scenario = _SCENARIOS[scenario_index]
    passage = scenario.passage()
    prompt, blueprint_options = _BLUEPRINTS[scenario.id][normalized_type]

    # The supported answer is always retained.  For the standard four-option
    # profile, omit only the last distractor; five-option keeps the authored set.
    selected_blueprints = list(blueprint_options)
    if profile.option_count < len(selected_blueprints):
        selected_blueprints = [selected_blueprints[0], *selected_blueprints[1:profile.option_count]]
    while len(selected_blueprints) < profile.option_count:
        selected_blueprints.append(_fallback_option(len(selected_blueprints) + 1, passage))

    quotes: list[str] = []
    for blueprint in selected_blueprints:
        for quote in blueprint.evidence_quotes:
            if quote not in quotes:
                quotes.append(quote)
    evidence, evidence_ids = _evidence_spans(passage, quotes)

    claims: list[Claim] = []
    raw_options: list[dict[str, Any]] = []
    raw_evaluations: list[AnswerEvaluation] = []
    for index, blueprint in enumerate(selected_blueprints, start=1):
        claim_id = f"claim-{index}"
        claim_evidence = tuple(evidence_ids[quote] for quote in blueprint.evidence_quotes)
        claim = Claim(
            claim_id,
            blueprint.text,
            blueprint.claim_type,
            blueprint.status,
            claim_evidence,
            blueprint.reasoning,
        )
        claims.append(claim)
        raw_options.append(
            {
                "id": "",
                "label": blueprint.text,
                "text": blueprint.text,
                "claimId": claim_id,
                "claimType": blueprint.claim_type,
                "evaluationStatus": blueprint.status,
                "evidence": list(claim_evidence),
                "distractorRationale": blueprint.rationale if blueprint.status != "supported" else "",
                "mutation": {
                    "kind": "correct" if blueprint.status == "supported" else "verbal-misreading",
                    "description": blueprint.rationale if blueprint.status != "supported" else "matches the passage and question",
                },
            }
        )
        raw_evaluations.append(
            AnswerEvaluation(
                "",
                claim_id,
                blueprint.status,
                blueprint.status == "supported",
                claim_evidence,
                blueprint.reasoning,
                blueprint.rationale if blueprint.status != "supported" else "",
            )
        )

    # Shuffle options and assign option IDs only after the correct claim is
    # known.  This keeps the answer position seed-dependent but the content
    # and evidence provenance stable.
    order = list(range(len(raw_options)))
    random.Random(seed + 7919 + len(normalized_type) * 17).shuffle(order)
    options: list[dict[str, Any]] = []
    evaluations: list[AnswerEvaluation] = []
    correct_option = ""
    for position, source_index in enumerate(order):
        option_id = chr(65 + position)
        option = dict(raw_options[source_index])
        option["id"] = option_id
        options.append(option)
        source_evaluation = raw_evaluations[source_index]
        evaluation = AnswerEvaluation(
            option_id,
            source_evaluation.claim_id,
            source_evaluation.status,
            source_evaluation.is_correct,
            source_evaluation.evidence_ids,
            source_evaluation.reasoning,
            source_evaluation.distractor_rationale,
        )
        evaluations.append(evaluation)
        if evaluation.is_correct:
            correct_option = option_id
    if not correct_option:
        raise ValueError("verbal blueprint must contain exactly one supported answer")

    correct_evaluation = next(item for item in evaluations if item.is_correct)
    correct_claim = next(item for item in claims if item.id == correct_evaluation.claim_id)
    cited = [span for span in evidence if span.id in correct_evaluation.evidence_ids]
    cited_text = "; ".join(f'“{span.text}”' for span in cited)
    type_sentence = {
        "reading-comprehension": "This is an explicit fact stated in the passage, so no extra assumption is needed.",
        "inference": "The conclusion follows from the cited facts without adding a cause, scope, or certainty that the passage does not provide.",
        "true-false": "Comparing the statement with the cited passage text shows that it is true; the other statements are contradicted or not stated.",
    }[normalized_type]
    invalid = tuple(
        f"Option {item.option_id}: {item.distractor_rationale}."
        for item in evaluations
        if not item.is_correct
    )
    reasoning_steps = (
        f"Identify the claim tested by option {correct_option}: {correct_claim.text}",
        f"Cite evidence {', '.join(correct_evaluation.evidence_ids)}: {cited_text}",
        type_sentence,
        "Reject each distractor because its evaluation records a contradiction, missing detail, or invalid inference.",
    )
    explanation_text = (
        f"Option {correct_option} is correct. Evidence {', '.join(correct_evaluation.evidence_ids)} states {cited_text}. "
        f"{type_sentence} "
        "The distractors are not supported: each one either contradicts an explicit fact or makes an invalid inference from it."
    )
    explanation = VerbalExplanation(
        explanation_text,
        reasoning_steps,
        tuple(correct_evaluation.evidence_ids),
        tuple(item.text for item in claims if item.explicit),
        invalid,
        correct_claim.text,
    )
    action = _explain_action(
        explanation,
        normalized_type,
        profile,
        evaluations,
        evidence,
        claims,
        correct_option,
    )
    distractors = [
        {
            "option": item.option_id,
            "reason": item.distractor_rationale,
            "description": item.distractor_rationale,
            "status": item.status,
            "claimId": item.claim_id,
            "evidence": list(item.evidence_ids),
        }
        for item in evaluations
        if not item.is_correct
    ]
    fragments = list(reasoning_steps)
    source_passage = passage.to_dict()
    evidence_signature = stable_signature(
        {
            "questionType": normalized_type,
            "scenario": scenario.id,
            "evidence": [span.to_dict() for span in cited],
        }
    )
    explanation_signature = stable_signature(
        {"questionType": normalized_type, "reasoningSteps": reasoning_steps}
    )
    metadata: dict[str, Any] = {
        "seed": seed,
        "examProfile": profile.name,
        "optionCount": profile.option_count,
        "questionType": normalized_type,
        "scenario": scenario.id,
        "sourcePassage": source_passage,
        "passage": source_passage,
        "claims": [item.to_dict() for item in claims],
        "evidenceSpans": [item.to_dict() for item in evidence],
        "answerEvaluation": [item.to_dict() for item in evaluations],
        "distractors": distractors,
        "distractorRationale": distractors,
        "explanationFragments": fragments,
        "reasoningSteps": fragments,
        "answerClaim": correct_claim.to_dict(),
        "answerEvidence": [item.to_dict() for item in cited],
        "answerSignature": evidence_signature,
        "answerValueSignature": stable_signature(correct_claim.to_dict()),
        "evidenceSignature": evidence_signature,
        "methodSignature": stable_signature({"questionType": normalized_type, "evidence": evidence_signature}),
        "explanationSignature": explanation_signature,
    }
    question_model = VerbalQuestion(
        id=f"verbal-{normalized_type}-{scenario.id}-{seed}-{level}",
        item_number=1,
        exam_profile=profile.name,
        option_count=profile.option_count,
        question_type=normalized_type,
        difficulty=level,
        passage=passage,
        question=prompt,
        claims=tuple(claims),
        evidence_spans=evidence,
        options=tuple(options),
        correct_option=correct_option,
        answer_evaluation=tuple(evaluations),
        explanation=explanation,
        actions={"explainLogic": action},
        metadata=metadata,
    )
    return question_model.to_dict()


# Family-local aliases mirror the naming used by the visual module when this
# module is consumed directly instead of through the package facade.
SUPPORTED_FORMATS = SUPPORTED_VERBAL_FORMATS
SUPPORTED_DIFFICULTIES = SUPPORTED_VERBAL_DIFFICULTIES


def generate_verbal(
    question_type: str = "reading-comprehension",
    seed: int = 0,
    difficulty: str | int = "medium",
    exam_profile: str | ExamProfile | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Short alias for :func:`generate_verbal_question`."""

    return generate_verbal_question(question_type, seed, difficulty, exam_profile, **kwargs)


def generate_reading_comprehension(**kwargs: Any) -> dict[str, Any]:
    return generate_verbal_question("reading-comprehension", **kwargs)


def generate_inference(**kwargs: Any) -> dict[str, Any]:
    return generate_verbal_question("inference", **kwargs)


def generate_true_false(**kwargs: Any) -> dict[str, Any]:
    return generate_verbal_question("true-false", **kwargs)


def explain_verbal_logic(question: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of the hidden verbal solution result."""

    try:
        action = question["actions"]["explainLogic"]
        if action["id"] != EXPLAIN_LOGIC_ACTION_ID:
            raise KeyError("unexpected action id")
        return deepcopy(action["result"])
    except (KeyError, TypeError) as error:
        raise ValueError("question has no Explain Logic action") from error


# Alternative names used by clients that call the review action a solution.
explain_verbal_reasoning = explain_verbal_logic
show_solution = explain_verbal_logic
generate_question = generate_verbal_question


__all__ = [
    "AnswerEvaluation",
    "Claim",
    "EXAM_PROFILES",
    "EXPLAIN_LOGIC_ACTION_ID",
    "Explanation",
    "EvidenceSpan",
    "ExamProfile",
    "HIDE_SOLUTION_ACTION_ID",
    "Passage",
    "SUPPORTED_DIFFICULTIES",
    "SUPPORTED_FORMATS",
    "SUPPORTED_VERBAL_DIFFICULTIES",
    "SUPPORTED_VERBAL_FORMATS",
    "SUPPORTED_VERBAL_QUESTION_TYPES",
    "SUPPORTED_VERBAL_TYPES",
    "VerbalAnswerEvaluation",
    "VerbalClaim",
    "VerbalEvidence",
    "VerbalEvidenceSpan",
    "VerbalExplanation",
    "VerbalOption",
    "VerbalPassage",
    "VerbalQuestion",
    "explain_verbal_logic",
    "explain_verbal_reasoning",
    "generate_inference",
    "generate_question",
    "generate_reading_comprehension",
    "generate_true_false",
    "generate_verbal",
    "generate_verbal_question",
    "show_solution",
    "resolve_exam_profile",
]
