import time  # noqa: F401  (you will time each tool call)
from collections.abc import Callable

from app.memory import ConversationStore
from app.providers import AgentError  # noqa: F401
from app.tools.placement_tools import PlacementTools

MAX_STEPS = 8

SYSTEM = """You are the Placement Assistant for an engineering college's placement cell.
You are talking to the student with roll number {student_id}. Act only for this student.
Use the tools for every fact about drives, eligibility, applications and slots; never guess.
Eligibility is decided by check_eligibility, not by you. Keep replies short and concrete."""


class Agent:
    """A small agent: one student, one conversation, the placement tools."""

    def __init__(self, provider, tools: PlacementTools, student_id: str,
                 memory: ConversationStore | None = None, thread_id: str | None = None,
                 on_step: Callable[[dict], None] | None = None):
        self.provider = provider
        self.tools = tools
        self.system = SYSTEM.format(student_id=student_id)
        self.memory = memory
        self.thread_id = thread_id
        self.on_step = on_step
        self.contents: list[dict] = []     # what the model sees, turn after turn
        self.trace: list[dict] = []        # what happened, step by step
        if self.memory and self.thread_id:
            self.contents = [{"role": message["role"], "text": message["text"]}
                             for message in self.memory.load_history(self.thread_id)]

    def _log(self, entry: dict) -> None:
        """Add one entry to the trace and tell on_step about it. (Given.)"""
        self.trace.append(entry)
        if self.on_step:
            self.on_step(entry)

    # ------------------------------------------------------------------ Part 2.1

    def run_tool(self, name: str, args: dict) -> dict:
        """Call one tool with self.tools.call(name, args). Never raise.

        (Part 2.1):
          - NotImplementedError -> {"error": "not_implemented", "hint": ...}
          - any other exception  -> {"error": "tool_failed", "hint": ...}
        A crash becomes information the model can act on: that is self-healing.
        """
        try:
            return self.tools.call(name, args)
        except NotImplementedError as e:
            return {"error": "not_implemented", "hint": str(e)}
        except Exception as e:
            return {"error": "tool_failed", "hint": str(e)}

    # ------------------------------------------------------------------ Part 2.2

    def ask(self, text: str) -> str:
        """One user turn: loop model calls and tool calls until the model answers.

        (Part 2.2):
          1. Append {"role": "user", "text": text} to self.contents.
          2. Call self.provider.generate(self.system, self.contents, list(self.tools.functions().values())).
             Log {"step", "kind": "model", "tokens_in", "tokens_out"}.
          3. No tool calls? Append {"role": "model", "text": reply, "raw": turn.raw} and return the reply.
          4. Otherwise append {"role": "model", "text": turn.text, "raw": turn.raw,
             "tool_calls": [{"name", "args"}, ...]}, then for EACH call, in order:
             run_tool, log {"step", "kind": "tool", "tool", "args", "result", "ok", "ms"}
             (ok means "error" not in result), and append {"role": "tool", "name", "result"}.
          5. Go back to 2. Steps are numbered 1, 2, 3... across model and tool steps.
          6. After MAX_STEPS steps without an answer, raise AgentError("step_limit", ...).

        TODO (Part 3.3), when self.memory is set: save the user message and start a run before
        the loop; record every model step and tool call as it happens; save the reply and finish
        the run as succeeded; on AgentError, finish the run as failed with e.code and re-raise.
        """
        run_id = None
        if self.memory and self.thread_id:
            self.memory.append_message(self.thread_id, "user", text)
            run_id = self.memory.start_run(self.thread_id, getattr(self.provider, "model", "unknown"))

        self.contents.append({"role": "user", "text": text})
        step = 0
        try:
            while step < MAX_STEPS:
                turn = self.provider.generate(
                    self.system, self.contents, list(self.tools.functions().values()))
                step += 1
                self._log({"step": step, "kind": "model",
                           "tokens_in": turn.tokens_in, "tokens_out": turn.tokens_out})
                if run_id:
                    self.memory.record_model_step(run_id, step, turn.tokens_in, turn.tokens_out)

                if not turn.tool_calls:
                    reply = turn.text or ""
                    self.contents.append({"role": "model", "text": reply, "raw": turn.raw})
                    if run_id:
                        self.memory.append_message(self.thread_id, "model", reply)
                        self.memory.finish_run(run_id, "succeeded")
                    return reply

                self.contents.append({
                    "role": "model",
                    "text": turn.text,
                    "raw": turn.raw,
                    "tool_calls": [{"name": call.name, "args": call.args} for call in turn.tool_calls],
                })
                for call in turn.tool_calls:
                    started = time.perf_counter()
                    result = self.run_tool(call.name, call.args)
                    elapsed_ms = int((time.perf_counter() - started) * 1000)
                    step += 1
                    ok = "error" not in result
                    self._log({"step": step, "kind": "tool", "tool": call.name,
                               "args": call.args, "result": result,
                               "ok": ok, "ms": elapsed_ms})
                    if run_id:
                        self.memory.record_tool_call(
                            run_id, step, call.name, call.args, result, ok, elapsed_ms)
                    self.contents.append({"role": "tool", "name": call.name, "result": result})

            raise AgentError("step_limit", f"Agent exceeded the {MAX_STEPS}-step limit.")
        except AgentError as error:
            if run_id:
                self.memory.finish_run(run_id, "failed", error.code)
            raise