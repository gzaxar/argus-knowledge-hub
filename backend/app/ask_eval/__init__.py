"""Ask ARGUS evaluation and model benchmark (docs/ask-eval.md).

Two questions, answered separately:

* release quality — does this version of ARGUS still answer a reviewed set of questions correctly and safely,
  with the production candidate model;
* model comparison — how do the approved chat models do on the same questions, with this version.

The questions are a versioned dataset (``data/v1``), asked through the real Ask flow and its real tools
(services/ask.py, services/mcp_tools.py) against synthetic workspaces built for the run and dropped after it.
Answers are scored by rules (``scoring``), optionally also by a judge model (``judge``); every run writes an
immutable JSON report and a readable one (``report``).
"""

DATASET_VERSION = "v1"
WORKSPACE_PREFIX = "askeval-"
