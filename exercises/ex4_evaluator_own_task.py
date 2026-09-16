"""EXERCISE 4 - Evaluator-Optimizer on your own task.   (about 25 minutes)

Pick a writing task from your own life - a leave letter, an internship cover
note, a project abstract, an event invitation - and define FOUR criteria.

At least one criterion must be OBJECTIVELY CHECKABLE (a word count, a required
phrase, a banned word). Vague criteria produce an evaluator that approves
everything, which costs you double for nothing.

CHECKPOINT
  [ ] Passes in 1-2 rounds with sensible criteria
  [ ] With one impossible criterion, stops at the cap and returns passed=False
  [ ] With vague criteria, approves immediately - observe it, and explain why

    python exercises/ex4_evaluator_own_task.py
"""

import _path  # noqa: F401
from agentcore import Agent, EvaluatorOptimizer

# ---------------------------------------------------------------- YOUR CODE
TASK = "TODO: describe the thing you want written, in one or two sentences."

CRITERIA = [
    "TODO: criterion 1 - make this one objectively checkable",
    "TODO: criterion 2",
    "TODO: criterion 3",
    "TODO: criterion 4",
]
# ------------------------------------------------------------ END YOUR CODE

if TASK.startswith("TODO"):
    raise SystemExit("Fill in TASK and CRITERIA first, then run this again.")

writer = Agent(
    name="Writer",
    instructions="You write clear, professional English.",
    temperature=0.7,
)

loop = EvaluatorOptimizer(generator=writer, criteria=CRITERIA, max_rounds=3)
outcome = loop.run(TASK)

print(f"\n  passed: {outcome['passed']}   rounds: {outcome['rounds']}\n")
print(outcome["output"])
print("\n--- review history ---")
for entry in outcome["history"]:
    print(f"  {entry}")
