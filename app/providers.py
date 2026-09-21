"""Where model turns come from.

Two providers with the same `generate(system, contents, tools)` shape:

  GeminiProvider  the real thing, used only for the optional `--real` check.
  RoutedMock      a scripted model. No key, no network, same answer every time.

The scripted provider is what makes the demo, the crash drill and the tests
runnable on a clean machine. It is also what makes them *assertable*: a real
model might phrase things differently on every run, so there would be nothing
stable to check a crash replay against.
"""
from dataclasses import dataclass, field
from typing import Any


class AgentError(Exception):
    """A run failed for a reason the worker should decide about.

    `retryable` is the interesting part: a rate limit is worth another attempt
    after a backoff, a malformed request is not.
    """

    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code, self.message, self.retryable = code, message, retryable


@dataclass
class ToolCall:
    name: str
    args: dict


@dataclass
class ModelTurn:
    text: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    raw: Any = None                 # the provider's own object, replayed verbatim


class GeminiProvider:
    """Real Gemini. Only used with `--real`; see README section 7."""

    def __init__(self, model: str):
        from google import genai
        self.client = genai.Client()
        self.model = model

    def _to_gemini(self, contents):
        from google.genai import types
        out = []
        for c in contents:
            if c["role"] == "user":
                out.append(types.Content(
                    role="user", parts=[types.Part.from_text(text=c["text"])]))
            elif c["role"] == "model":
                if c.get("raw") is not None:
                    out.append(c["raw"])            # keep the original parts intact
                    continue
                parts = [types.Part.from_text(text=c["text"])] if c.get("text") else []
                parts += [types.Part.from_function_call(name=t["name"], args=t["args"])
                          for t in c.get("tool_calls", [])]
                out.append(types.Content(role="model", parts=parts))
            elif c["role"] == "tool":
                out.append(types.Content(role="user", parts=[
                    types.Part.from_function_response(name=c["name"], response=c["result"])]))
        return out

    def generate(self, system, contents, tools) -> ModelTurn:
        from google.genai import errors, types
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=self._to_gemini(contents),
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    tools=tools,
                    temperature=0,
                    # We drive the tool loop ourselves, because every call has to
                    # be recorded with its idempotency key before it runs.
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                ),
            )
        except errors.APIError as exc:
            if exc.code == 429:
                raise AgentError("provider_rate_limited", "Model quota exhausted", retryable=True)
            if exc.code and exc.code >= 500:
                raise AgentError("provider_unavailable", "Model provider failed", retryable=True)
            raise AgentError("provider_error", str(exc))

        content = response.candidates[0].content if response.candidates else None
        parts = (content.parts or []) if content else []
        text = "".join(p.text for p in parts if p.text and not p.thought) or None
        calls = [ToolCall(fc.name, dict(fc.args or {})) for fc in (response.function_calls or [])]
        usage = response.usage_metadata
        return ModelTurn(
            text, calls,
            (usage.prompt_token_count or 0) if usage else 0,
            (usage.candidates_token_count or 0) if usage else 0,
            content,
        )


class RoutedMock:
    """A scripted model.

    It looks at the most recent user message, matches it to a route, and plays
    that route's turns in order. Position is counted from how many model turns
    are already in `contents`, so a replayed run resumes at the right line
    instead of starting the script again.
    """

    model = "mock"

    def __init__(self, routes: dict[str, list[ModelTurn]], slow: float = 0.0):
        self.routes, self.slow = routes, slow
        self.calls: list[list[dict]] = []       # kept so tests can inspect prompts

    def generate(self, system, contents, tools) -> ModelTurn:
        import time

        self.calls.append([dict(c) for c in contents])
        last_user = max(i for i, c in enumerate(contents) if c["role"] == "user")
        request = contents[last_user]["text"]
        position = sum(1 for c in contents[last_user:] if c["role"] == "model")

        if self.slow:
            time.sleep(self.slow)               # used to test cancellation

        for phrase, turns in self.routes.items():
            if phrase.lower() in request.lower():
                return turns[position] if position < len(turns) else ModelTurn("(mock) done.")
        return ModelTurn("(mock) no scripted route for that request.")


def call(name: str, **args) -> ModelTurn:
    """Shorthand for 'the model asked for this one tool'."""
    return ModelTurn(None, [ToolCall(name, args)], tokens_in=100, tokens_out=10)


def demo_providers(slow: float = 0.0) -> dict:
    """One scripted model per agent.

    Each route is a small conversation: what the supervisor does, and what each
    specialist does once the supervisor delegates to it. Routing works by
    substring match on the student's own words (see `RoutedMock` above), so a
    few natural phrasings are mapped to the same conversation to keep
    `scripts.ask` usable without memorising exact trigger words.
    """
    check_balance = [
        call("ask_balance", question="Check my leave balance"),
        ModelTurn("You have leave days remaining, as shown in your leave record."),
    ]
    show_history = [
        call("ask_balance", question="Show my leave requests"),
        ModelTurn("Your leave requests and their statuses are listed above."),
    ]

    supervisor = RoutedMock({
        # Apply: look before you leap, then delegate the write.
        "apply": [
            call("ask_balance", question="Check my leave balance"),
            call("ask_desk", request=(
                "Apply leave from 2026-09-21 to 2026-09-23 for 3 days for a "
                "family function and notify the HOD.")),
            ModelTurn("Your leave for 21-23 September was applied and the HOD was notified."),
        ],
        # A pure question never reaches the desk specialist at all. Several
        # everyday phrasings of the same question all land here.
        "balance": check_balance,
        "how many leave": check_balance,
        "days do i have": check_balance,
        "history": show_history,
        "my requests": show_history,
        "withdraw": [
            call("ask_balance", question="Show my leave requests"),
            call("ask_desk", request="Withdraw leave request 1 and notify the HOD."),
            ModelTurn("That leave request was withdrawn and the HOD was notified."),
        ],
        # Over the policy limit: the tool refuses and the supervisor relays it.
        "long leave": [
            call("ask_desk", request=(
                "Apply leave from 2026-11-01 to 2026-11-10 for 9 days for travel.")),
            ModelTurn("That request is longer than the policy allows, so it was not applied."),
        ],
    }, slow)

    balance = RoutedMock({
        "Check my leave balance": [
            call("get_leave_balance"),
            ModelTurn("The leave record shows the current balance."),
        ],
        "Show my leave requests": [
            call("get_leave_requests"),
            ModelTurn("Those are the student's leave requests."),
        ],
        "holiday": [
            call("holiday_calendar", start_date="2026-09-01", end_date="2026-12-31"),
            ModelTurn("Those are the holidays in that range."),
        ],
    }, slow)

    desk = RoutedMock({
        "Apply leave from 2026-09-21": [
            call("get_leave_balance"),
            call("apply_leave", start_date="2026-09-21", end_date="2026-09-23",
                 days=3, reason="family function"),
            call("notify_hod", message=(
                "Leave for 2026-09-21 to 2026-09-23 (3 days) has been applied.")),
            ModelTurn("Applied the leave and notified the HOD."),
        ],
        "Apply leave from 2026-11-01": [
            call("apply_leave", start_date="2026-11-01", end_date="2026-11-10",
                 days=9, reason="travel"),
            ModelTurn("The leave desk refused that request: it exceeds the policy limit."),
        ],
        "Withdraw leave": [
            call("withdraw_leave", request_id=1),
            call("notify_hod", message="Leave request 1 has been withdrawn."),
            ModelTurn("Withdrew leave request 1 and notified the HOD."),
        ],
    }, slow)

    return {"supervisor": supervisor, "balance": balance, "desk": desk}
