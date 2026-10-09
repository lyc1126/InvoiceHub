# CLAUDE.md

Read [AGENTS.md](AGENTS.md) in full before analysis, edits, tests, or conclusions. It contains the common project boundaries, Git/authorization rules, verification requirements, and closeout workflow for every coding agent.

## Read only the relevant feature rules

1. Check live Git status, branch, HEAD, and existing changes as required by AGENTS.md. Do not infer the workspace from another session.
2. Use the [task quick lookup](docs/architecture/AGENT_TASK_MAP.md#quick-lookup) to match the symptom or change. Read every matched rule page in `docs/architecture/rules/` in full, then its linked task row for code entry points, dependencies, and minimum acceptance.
3. For architecture, cross-module, data-flow, startup, monitor, and release tasks, also read [the architecture entry](docs/DEVELOPMENT_ARCHITECTURE.md). Follow its relevant maps and the additional truth documents required by AGENTS.md.
4. Before Git mutations, read [the Git operation rules](docs/GIT_BRANCH_WORKTREE_FORK_GUIDE.md#git-rules). User instructions about the current task remain authoritative; examples do not authorize a push, merge, or external operation.

## Architecture quick lookup

| Map | Answers |
|---|---|
| `docs/architecture/AGENT_TASK_MAP.md` | task → first-read sections, entry symbols, linkage, minimum test and acceptance |
| `docs/architecture/FILE_MAP.md` | what every file is responsible for and its neighbours |
| `docs/architecture/INTERFACES_AND_FLOWS.md` | page routes, HTTP API table, error model, SSE, runtime sequences |
| `docs/architecture/DATA_AND_ALGORITHMS.md` | truth hierarchy, models, SQLite schema, projection fields, formulas, rounding |
| `docs/architecture/COMMENT_RATIONALE_MAP.md` | non-obvious invariants, compatibility reasons, failure guards, guarding tests |
| `docs/DEVELOPMENT_ARCHITECTURE.md` | the entry point that binds those appendices to the current implementation |

Search by symptom, symbol, or path with `rg -n '<keyword>' docs/architecture/`; open the matched rule section and source/tests before making a conclusion.


## Maintenance

Keep this file as an entry point. Global rules belong in AGENTS.md; feature constraints belong in their scoped rule page, with task/map links updated in the same task. Follow AGENTS.md for CHANGELOG, implementation status, tests, and workspace classification. Update the GitHub README only for a directly related major product update or an explicit user request.
