"""Local learner-facing web app for the deterministic EPSO generators.

The browser receives only the question presentation.  The complete generator
payload stays in this process until the learner submits an answer and asks for
an explanation, so the client never reimplements question logic.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse

from . import (
    SUPPORTED_DIFFICULTIES,
    SUPPORTED_EXAM_PROFILES,
    SUPPORTED_FORMATS,
    SUPPORTED_NUMERICAL_FORMATS,
    SUPPORTED_NUMERICAL_OPERATIONS,
    SUPPORTED_VERBAL_QUESTION_TYPES,
    generate_numerical_question,
    generate_question,
    generate_verbal_question,
)


STATIC_ROOT = Path(__file__).with_name("web")
_MAX_QUESTIONS = 256
_QUESTIONS: dict[str, dict[str, Any]] = {}


class APIError(ValueError):
    """An expected request error that should be returned as JSON."""


def _query_value(query: Mapping[str, list[str]], name: str, default: str) -> str:
    value = query.get(name, [default])[0]
    return str(value).strip() or default


def _public_option(option: Mapping[str, Any]) -> dict[str, Any]:
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


def _public_question(question: Mapping[str, Any], token: str) -> dict[str, Any]:
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
    public["options"] = [_public_option(option) for option in public.get("options", ())]

    # The source passage/table/chart remains available as stimulus data, but
    # evidence annotations and the answer-bearing metadata do not.
    if isinstance(public.get("stimulus"), dict):
        public["stimulus"].pop("evidenceSpans", None)
        if isinstance(public["stimulus"].get("passage"), dict):
            public["stimulus"]["passage"].pop("evidenceSpans", None)
    public["metadata"] = {
        key: public.get("metadata", {}).get(key)
        for key in ("seed", "examProfile", "optionCount", "operation", "questionType")
        if key in public.get("metadata", {})
    }
    action = public.get("actions", {}).get("explainLogic")
    if isinstance(action, dict):
        action.pop("result", None)
        action["solutionView"] = {
            "initiallyVisible": False,
            "hideAction": action.get("solutionView", {}).get("hideAction", {}),
        }
    public["solutionToken"] = token
    return public


def _generate_question(query: Mapping[str, list[str]]) -> tuple[str, dict[str, Any]]:
    family = _query_value(query, "family", "visual").lower()
    seed_text = _query_value(query, "seed", "42")
    try:
        seed = int(seed_text)
    except ValueError as error:
        raise APIError("seed must be an integer") from error
    difficulty = _query_value(query, "difficulty", "medium").lower()
    profile = _query_value(query, "profile", "standard").lower()
    if difficulty not in SUPPORTED_DIFFICULTIES:
        raise APIError(f"difficulty must be one of: {', '.join(SUPPORTED_DIFFICULTIES)}")
    if profile not in SUPPORTED_EXAM_PROFILES:
        raise APIError(f"profile must be one of: {', '.join(SUPPORTED_EXAM_PROFILES)}")

    try:
        if family == "visual":
            format_name = _query_value(query, "format", "sequence")
            if format_name not in SUPPORTED_FORMATS:
                raise APIError(f"visual format must be one of: {', '.join(SUPPORTED_FORMATS)}")
            question = generate_question(
                format_name, seed=seed, difficulty=difficulty, exam_profile=profile
            )
        elif family == "numerical":
            operation = _query_value(query, "operation", "percentage-change")
            representation = _query_value(query, "representation", "table")
            if operation not in SUPPORTED_NUMERICAL_OPERATIONS:
                raise APIError(
                    "numerical operation must be one of: "
                    + ", ".join(SUPPORTED_NUMERICAL_OPERATIONS)
                )
            if representation not in SUPPORTED_NUMERICAL_FORMATS:
                raise APIError(
                    "representation must be one of: "
                    + ", ".join(SUPPORTED_NUMERICAL_FORMATS)
                )
            question = generate_numerical_question(
                operation,
                seed=seed,
                difficulty=difficulty,
                exam_profile=profile,
                representation=representation,
            )
        elif family == "verbal":
            question_type = _query_value(query, "questionType", "reading-comprehension")
            if question_type not in SUPPORTED_VERBAL_QUESTION_TYPES:
                raise APIError(
                    "verbal type must be one of: "
                    + ", ".join(SUPPORTED_VERBAL_QUESTION_TYPES)
                )
            question = generate_verbal_question(
                question_type, seed=seed, difficulty=difficulty, exam_profile=profile
            )
        else:
            raise APIError("family must be visual, numerical, or verbal")
    except (TypeError, ValueError) as error:
        raise APIError(str(error)) from error

    token = secrets.token_urlsafe(24)
    if len(_QUESTIONS) >= _MAX_QUESTIONS:
        _QUESTIONS.pop(next(iter(_QUESTIONS)))
    _QUESTIONS[token] = question
    return token, _public_question(question, token)


def _solution(token: str, selected_option: str) -> dict[str, Any]:
    question = _QUESTIONS.get(token)
    if question is None:
        raise APIError("question has expired; generate a new question")
    selected = str(selected_option or "").strip().upper()
    option_ids = {str(option.get("id")) for option in question.get("options", ())}
    if selected and selected not in option_ids:
        raise APIError("selectedOption must identify one of the displayed options")
    result = deepcopy(question["actions"]["explainLogic"]["result"])
    result["selectedOption"] = selected or None
    result["isCorrect"] = (selected == question["correctOption"]) if selected else None
    result["selectedReason"] = (
        "Your answer matches the correct option."
        if result["isCorrect"] is True
        else f"You selected option {selected}; the correct answer is option {question['correctOption']}."
        if selected
        else "Solution preference is enabled. Select an answer to check your response."
    )
    return result


def _json_response(handler: BaseHTTPRequestHandler, payload: Mapping[str, Any], status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class EPSORequestHandler(BaseHTTPRequestHandler):
    """Serve static assets and the small JSON API."""

    server_version = "epsotests-web/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        # Keep the local run command quiet enough to read while retaining the
        # standard server hook for subclasses and tests.
        return

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/health":
                _json_response(self, {"ok": True, "service": "epsotests-web"})
                return
            if parsed.path == "/api/question":
                token, question = _generate_question(parse_qs(parsed.query))
                _json_response(self, {"question": question, "solutionToken": token})
                return
            self._serve_static(parsed.path)
        except APIError as error:
            _json_response(self, {"error": str(error)}, 400)
        except Exception:
            _json_response(self, {"error": "unable to generate this question"}, 500)

    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        parsed = urlparse(self.path)
        if parsed.path != "/api/solution":
            _json_response(self, {"error": "not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 32_000:
                raise APIError("request body is too large")
            payload = json.loads(self.rfile.read(length) or b"{}")
            result = _solution(payload.get("solutionToken", ""), payload.get("selectedOption", ""))
            _json_response(self, {"solution": result})
        except (json.JSONDecodeError, TypeError) as error:
            _json_response(self, {"error": "request body must be JSON"}, 400)
        except APIError as error:
            _json_response(self, {"error": str(error)}, 400)

    def _serve_static(self, path: str) -> None:
        relative = path.removeprefix("/") or "index.html"
        candidate = (STATIC_ROOT / relative).resolve()
        root = STATIC_ROOT.resolve()
        if root != candidate and root not in candidate.parents:
            _json_response(self, {"error": "not found"}, 404)
            return
        if not candidate.is_file():
            _json_response(self, {"error": "not found"}, 404)
            return
        content_type = {
            ".css": "text/css; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".html": "text/html; charset=utf-8",
            ".svg": "image/svg+xml",
        }.get(candidate.suffix, "application/octet-stream")
        body = candidate.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local epsotests learner web app")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), EPSORequestHandler)
    print(f"epsotests web app: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
