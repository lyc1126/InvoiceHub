#!/usr/bin/env python3
"""Offline, vendor-neutral task checkpoints. Python 3.10+, standard library only."""
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
import uuid
from urllib.parse import unquote, urlsplit

VERSION = "1.1.0"
SCHEMA = "agent-handoff/v2"
LEGACY_SCHEMA = "agent-handoff/v1"
BRIEF_CHARS = 3000
MAX_JSON = 32 * 1024 * 1024
MAX_FILES = 10000
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
STATUSES = {"active", "ready_for_handoff", "blocked", "completed"}
NOTE_FIELDS = {
    "goal", "acceptance_criteria", "constraints", "authorizations", "decisions",
    "attempts", "changes", "verification", "open_questions", "next_steps", "processes",
}


class HandoffError(Exception):
    pass


def fail(message):
    raise HandoffError(message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
        fail("INVALID_ID: use 1-64 ASCII letters, digits, underscores or hyphens")
    if value.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10))}:
        fail("INVALID_ID: reserved platform filename")
    return value


def nonempty(value, field):
    if not isinstance(value, str) or not value.strip() or len(value) > 20000:
        fail(f"INVALID_FIELD: {field} must be nonempty text, at most 20000 characters")
    return value


def reject_link(path):
    if path.is_symlink():
        fail(f"UNSAFE_LINK: {path.name}")
    if path.exists() and getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
        fail(f"UNSAFE_REPARSE_POINT: {path.name}")


def inside(path, parent):
    return path == parent or parent in path.parents


def read_json(path):
    reject_link(path)
    if path.stat().st_size > MAX_JSON:
        fail("SIZE_LIMIT: JSON exceeds 32 MiB")
    return decode_json(path.read_text(encoding="utf-8"))


def decode_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                fail(f"DUPLICATE_JSON_KEY: {key}")
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique,
                      parse_constant=lambda x: fail(f"INVALID_JSON_NUMBER: {x}"))


def atomic_write(path, data):
    reject_link(path)
    if path.is_file() and path.read_bytes() == data:
        return False
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("xb") as stream:
            if os.name != "nt":
                os.chmod(temp, 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        sync_dir(path.parent)
    finally:
        if temp.exists():
            temp.unlink()
    return True


def sync_dir(path):
    if os.name != "nt":
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


@contextlib.contextmanager
def state_root_lock(directory):
    path = directory / ".write.lock"
    reject_link(path)
    stream = path.open("a+b")
    if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) != 0o600:
        os.chmod(path, 0o600)
    if path.stat().st_size == 0:
        stream.write(b"0")
        stream.flush()
    locked = False
    deadline = time.monotonic() + 5
    try:
        while not locked:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except OSError:
                if time.monotonic() >= deadline:
                    fail("STORE_BUSY: another command holds the project write lock")
                time.sleep(0.05)
        yield
    finally:
        if locked:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


def git(workspace, *args, optional=False):
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
    # The explicit workspace is authoritative. Ambient worktree/index overrides
    # from another agent must not silently redirect the identity being captured.
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_PREFIX"):
        env.pop(key, None)
    try:
        result = subprocess.run(["git", "--no-optional-locks", "-C", str(workspace), *args],
                                capture_output=True, timeout=30, env=env)
    except FileNotFoundError:
        if optional:
            return None
        fail("GIT_UNAVAILABLE: install Git or explicitly use --no-git with --scope")
    if result.returncode:
        if optional:
            return None
        fail(f"GIT_FAILED: {args[0]} exited {result.returncode}")
    return result.stdout


def resolve_workspace(path):
    resolved = Path(path).expanduser().resolve(strict=True)
    if not resolved.is_dir():
        fail("INVALID_WORKSPACE: expected an existing directory")
    return resolved


def validate_scope(scope):
    if not isinstance(scope, list) or len(scope) > 1000:
        fail("INVALID_SCOPE: expected a list of relative files/directories")
    for item in scope:
        if not isinstance(item, str) or not item or "\\" in item or ":" in item or item.startswith("/") or any(p in {"", ".", "..", ".git"} for p in item.split("/")):
            fail("INVALID_SCOPE: use relative POSIX paths, without traversal or .git")


def snapshot(workspace, scope, no_git=False):
    workspace = resolve_workspace(workspace)
    validate_scope(scope)
    head = None if no_git else git(workspace, "rev-parse", "--show-toplevel", optional=True)
    git_info = None
    if head is not None:
        top = Path(head.decode().strip()).resolve()
        if top != workspace:
            fail("WORKSPACE_NOT_GIT_ROOT: select the repository root")
        git_info = {
            "head": git(workspace, "rev-parse", "--verify", "HEAD", optional=True),
            "branch": git(workspace, "symbolic-ref", "--short", "HEAD", optional=True),
            "index_sha256": hashlib.sha256(git(workspace, "ls-files", "--stage", "-z")).hexdigest(),
        }
        for key in ("head", "branch"):
            git_info[key] = git_info[key].decode().strip() if git_info[key] else None
        names = git(workspace, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
        candidates = sorted(set(os.fsdecode(n) for n in names.split(b"\0") if n))
        if scope:
            candidates = [n for n in candidates if any(n == s or n.startswith(s + "/") for s in scope)]
    else:
        if not no_git and (workspace / ".git").exists():
            fail("GIT_UNAVAILABLE: repository detected; use Git or explicitly --no-git --scope")
        if not scope:
            fail("SCOPE_REQUIRED: non-Git workspaces require explicit --scope paths")
        candidates = []
        for entry in scope:
            path = workspace / entry
            if path.is_dir() and not path.is_symlink():
                for current, dirs, files in os.walk(path, followlinks=False):
                    dirs[:] = sorted(d for d in dirs if d not in {".git", "__pycache__", ".venv", "node_modules"})
                    candidates.extend((Path(current) / n).relative_to(workspace).as_posix() for n in files)
                    if len(candidates) > MAX_FILES:
                        fail("SIZE_LIMIT: scope contains too many files")
            else:
                candidates.append(entry)
        candidates = sorted(set(candidates))
    if len(candidates) > MAX_FILES:
        fail("SIZE_LIMIT: over 10000 files; select a narrower --scope")
    files = {}
    total = 0
    for name in candidates:
        path = workspace / name
        if not inside(path.parent.resolve(), workspace):
            fail(f"SOURCE_ESCAPES_WORKSPACE: {name}")
        if path.is_symlink():
            files[name] = {"kind": "symlink", "sha256": hashlib.sha256(os.fsencode(os.readlink(path))).hexdigest()}
        elif not path.exists():
            files[name] = {"kind": "missing"}
        elif path.is_dir():
            # Git submodule contents need their own task; the index still binds
            # the gitlink. Never claim that their uncommitted contents were read.
            fail(f"NESTED_WORKSPACE: {name}; narrow scope and register a separate task")
        else:
            before = path.stat()
            if not stat.S_ISREG(before.st_mode):
                fail(f"UNSUPPORTED_FILE: {name}")
            total += before.st_size
            if before.st_size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                fail("SIZE_LIMIT: narrow scope; source files are never truncated")
            h = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    h.update(chunk)
            after = path.stat()
            if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
                fail("WORKSPACE_CHANGED_DURING_CAPTURE: retry after writers stop")
            files[name] = {"kind": "file", "sha256": h.hexdigest(), "size": after.st_size,
                           "executable": bool(after.st_mode & 0o111)}
    result = {"workspace": str(workspace), "scope": scope, "no_git": no_git, "git": git_info, "files": files}
    result["fingerprint"] = digest(result)
    return result


def notes_template(goal="Describe the requested outcome"):
    return {
        "goal": goal,
        "acceptance_criteria": ["Describe the observable completion criteria"],
        "constraints": [], "authorizations": [], "decisions": [], "attempts": [],
        "changes": [], "verification": [], "open_questions": [], "processes": [],
        "next_steps": ["Describe the first concrete action and its expected result"],
    }


def validate_notes(notes):
    if not isinstance(notes, dict) or set(notes) != NOTE_FIELDS:
        fail("INVALID_NOTES: use template; all standard fields are required")
    nonempty(notes["goal"], "goal")
    for key in NOTE_FIELDS - {"goal"}:
        if not isinstance(notes[key], list) or len(notes[key]) > 200:
            fail(f"INVALID_NOTES: {key} must be a list of at most 200 text entries")
        for entry in notes[key]:
            nonempty(entry, key)
    if not notes["acceptance_criteria"] or not notes["next_steps"]:
        fail("INVALID_NOTES: acceptance_criteria and next_steps cannot be empty")
    if len(canonical(notes)) > 256 * 1024:
        fail("SIZE_LIMIT: notes exceed 256 KiB")


def validate_state(state):
    expected = {"schema", "project", "task", "title", "revision", "status", "owner", "updated_at", "notes", "snapshot", "operations"}
    if isinstance(state, dict) and state.get("schema") == SCHEMA:
        expected.add("references")
    if not isinstance(state, dict) or set(state) != expected or state.get("schema") not in {SCHEMA, LEGACY_SCHEMA}:
        fail("INVALID_SCHEMA: unsupported/corrupt checkpoint; preserve source")
    refs = state.get("references", [])
    if not isinstance(refs, list) or len(refs) > 32:
        fail("INVALID_SCHEMA: at most 32 references per task")
    keys = [reference_key(ref) for ref in refs]
    if len(keys) != len(set(keys)):
        fail("INVALID_SCHEMA: duplicate references")
    identifier(state["project"]); identifier(state["task"])
    nonempty(state["title"], "title"); nonempty(state["updated_at"], "updated_at")
    if type(state["revision"]) is not int or state["revision"] < 1 or state["status"] not in STATUSES:
        fail("INVALID_SCHEMA: invalid revision/status")
    if state["owner"] is not None:
        nonempty(state["owner"], "owner")
    validate_notes(state["notes"])
    snap = state["snapshot"]
    if not isinstance(snap, dict) or set(snap) != {"workspace", "scope", "no_git", "git", "files", "fingerprint"}:
        fail("INVALID_SCHEMA: invalid snapshot")
    if not isinstance(snap["workspace"], str) or not (Path(snap["workspace"]).is_absolute() or PureWindowsPath(snap["workspace"]).is_absolute()):
        fail("INVALID_SCHEMA: workspace must be absolute on this host")
    validate_scope(snap["scope"])
    if type(snap["no_git"]) is not bool or not isinstance(snap["files"], dict) or len(snap["files"]) > MAX_FILES:
        fail("INVALID_SCHEMA: invalid file manifest")
    raw = {k: v for k, v in snap.items() if k != "fingerprint"}
    if snap["fingerprint"] != digest(raw):
        fail("INVALID_SCHEMA: snapshot fingerprint mismatch")
    for name, info in snap["files"].items():
        validate_scope([name])
        if not isinstance(info, dict) or info.get("kind") not in {"file", "symlink", "missing"}:
            fail("INVALID_SCHEMA: invalid file entry")
    if not isinstance(state["operations"], dict) or len(state["operations"]) > 1000:
        fail("INVALID_SCHEMA: invalid operations")
    for key, op in state["operations"].items():
        identifier(key)
        if not isinstance(op, dict) or set(op) != {"state", "detail", "updated_at"} or op["state"] not in {"started", "confirmed", "failed_confirmed", "unknown"}:
            fail("INVALID_SCHEMA: invalid operation")
        nonempty(op["detail"], "operation evidence")


LABELS = {
    "goal": "目标 / Goal", "acceptance_criteria": "完成标准 / Acceptance",
    "constraints": "约束 / Constraints", "authorizations": "授权来源与范围 / Authorization evidence",
    "decisions": "结论、理由与证据 / Decisions", "attempts": "已尝试与排除 / Attempts",
    "changes": "修改及归属 / Changes", "verification": "验证及适用代码状态 / Verification",
    "open_questions": "未决问题 / Open questions", "next_steps": "下一步 / Next steps",
    "processes": "进行中的进程与操作 / Processes",
}


def task_reference(project, task):
    return f"handoff://{identifier(project)}/{identifier(task)}"


def reference_key(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        fail("INVALID_REFERENCE: expected a link or ID up to 2048 characters")
    value = value.strip().strip("<>")
    if value.startswith("handoff://"):
        parsed = urlsplit(value)
        if parsed.query or parsed.fragment:
            fail("INVALID_REFERENCE: task links do not accept query or fragment")
        return task_reference(unquote(parsed.netloc), unquote(parsed.path.lstrip("/")))
    ids = {item.lower() for item in re.findall(r"(?i)(?<![0-9a-f])[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}(?![0-9a-f])", value)}
    if len(ids) > 1:
        fail("INVALID_REFERENCE: multiple IDs; provide the exact task link or one ID")
    return "id:" + next(iter(ids)).lower() if ids else "alias:" + value


def delta_between(before, after):
    put, edit = {}, {}
    for key, value in after.items():
        if key in before and before[key] == value:
            continue
        if key in before and isinstance(before[key], dict) and isinstance(value, dict):
            edit[key] = delta_between(before[key], value)
        else:
            put[key] = value
    return {"put": put, "edit": edit, "drop": sorted(set(before) - set(after))}


def apply_delta(before, delta, depth=0):
    if depth > 20 or not isinstance(delta, dict) or set(delta) != {"put", "edit", "drop"}:
        fail("INVALID_DELTA: unknown patch structure")
    put, edit, drop = delta["put"], delta["edit"], delta["drop"]
    if not isinstance(put, dict) or not isinstance(edit, dict) or not isinstance(drop, list) or any(not isinstance(k, str) for k in drop):
        fail("INVALID_DELTA: invalid patch types")
    if len(drop) != len(set(drop)) or set(put) & set(edit) or (set(put) | set(edit)) & set(drop):
        fail("INVALID_DELTA: overlapping operations")
    result = dict(before)
    for key in drop:
        if key not in before:
            fail("INVALID_DELTA: missing removal target")
        del result[key]
    result.update(put)
    for key, patch in edit.items():
        if not isinstance(before.get(key), dict):
            fail("INVALID_DELTA: missing dictionary target")
        result[key] = apply_delta(before[key], patch, depth + 1)
    return result


def brief(state, max_chars=BRIEF_CHARS):
    if not 2000 <= max_chars <= 20000:
        fail("INVALID_BUDGET: --max-chars must be 2000..20000")
    pending = [key for key, op in state["operations"].items() if op["state"] in {"started", "unknown"}]
    packet = {"schema": "agent-handoff/brief-v1", "task_ref": task_reference(state["project"], state["task"]),
              "revision": state["revision"], "status": state["status"], "owner": state["owner"],
              "workspace": state["snapshot"]["workspace"], "fingerprint": state["snapshot"]["fingerprint"],
              "pending_operations_count": len(pending), "pending_operations": pending[:8],
              "live_check": "not_run", "notes": {}, "omitted_fields": [], "expand_before_action": False,
              "detail": "show --task <id> --section <field>; claim verifies live files"}
    omitted = set()
    if len(pending) > 8:
        omitted.add("operations")
    priority = ["goal", "next_steps", "constraints", "authorizations", "open_questions", "processes",
                "acceptance_criteria", "verification", "decisions", "changes", "attempts"]
    for key in priority:
        value = state["notes"][key]
        entries = [value] if isinstance(value, str) else list(dict.fromkeys(value))
        if key in {"verification", "decisions", "changes", "attempts"}:
            entries = entries[-3:]
            if len(value) > len(entries):
                omitted.add(key)
        selected = []
        for entry in entries:
            cut = entry[:320] + ("…" if len(entry) > 320 else "")
            packet["notes"][key] = cut if key == "goal" else selected + [cut]
            if len(canonical(packet).decode()) + 350 > max_chars:
                if selected:
                    packet["notes"][key] = selected
                else:
                    packet["notes"].pop(key, None)
                omitted.add(key)
                break
            selected.append(cut)
            if cut != entry:
                omitted.add(key)
    packet["omitted_fields"] = sorted(omitted)
    packet["expand_before_action"] = bool(omitted & {"goal", "next_steps", "constraints", "authorizations", "open_questions", "processes", "operations"})
    if len(canonical(packet).decode()) > max_chars:
        fail("BRIEF_METADATA_TOO_LARGE: use --max-chars with a larger budget")
    return packet


def render(state):
    return f"# {state['title'][:100]}\nRevision: {state['revision']} | {state['status']}\n\n```json\n{canonical(brief(state)).decode()}\n```\n"


class Store:
    def __init__(self, state_root, project):
        identifier(project)
        declared = Path(state_root).expanduser()
        reject_link(declared)
        self.root = declared.resolve()
        self.project = project
        self._history_cache = {}
        self.directory = self.root / project
        self.tasks = self.directory / "tasks"
        for path in (self.directory, self.tasks):
            reject_link(path)
        existing = self.root
        while not existing.exists():
            existing = existing.parent
        if git(existing, "rev-parse", "--show-toplevel", optional=True):
            fail("PRIVATE_STATE_INSIDE_GIT: ignored directories are not private storage")

    def outside_workspace(self, workspace):
        workspace = Path(workspace).expanduser().resolve()
        roots = [workspace]
        worktrees = git(workspace, "worktree", "list", "--porcelain", optional=True)
        if worktrees:
            roots += [Path(line[9:]).resolve() for line in os.fsdecode(worktrees).splitlines() if line.startswith("worktree ")]
        for target in roots:
            if inside(self.root, target) or inside(target, self.root):
                fail("PRIVATE_STATE_OVERLAPS_WORKSPACE: choose a separate private directory")

    def prepare(self):
        for path in (self.root, self.directory, self.tasks):
            reject_link(path)
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            os.chmod(self.directory, 0o700); os.chmod(self.tasks, 0o700)

    def task_dir(self, task):
        path = self.tasks / identifier(task)
        reject_link(path)
        return path

    def history(self, task):
        path = self.task_dir(task) / "EVENTS.jsonl"
        reject_link(path)
        if not path.is_file():
            fail("TASK_NOT_FOUND: no task journal")
        info = path.stat()
        key = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        cached = self._history_cache.get(task)
        if cached and cached[0] == key:
            return cached[1]
        if info.st_size > MAX_JSON:
            fail("SIZE_LIMIT: journal exceeds 32 MiB; preserve it and start a linked task")
        raw = path.read_bytes()
        after = path.stat()
        if key != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            fail("JOURNAL_CHANGED_DURING_READ: retry once the writer has finished")
        records = self.decode_history(task, raw)
        self._history_cache[task] = (key, records)
        return records

    def decode_history(self, task, raw):
        if not raw.endswith(b"\n"):
            fail("INCOMPLETE_JOURNAL_TAIL: inspect then repair --discard-incomplete-tail")
        previous = "0" * 64
        records = []
        for revision, line in enumerate(raw.splitlines(), 1):
            event = decode_json(line)
            base_keys = {"schema", "revision", "previous_hash", "event", "actor", "hash"}
            if not isinstance(event, dict) or set(event) not in (base_keys | {"state"}, base_keys | {"delta"}):
                fail("INVALID_JOURNAL: unexpected event fields")
            claimed = event["hash"]
            content = {k: v for k, v in event.items() if k != "hash"}
            if event["schema"] not in {SCHEMA, LEGACY_SCHEMA} or type(event["revision"]) is not int or event["revision"] != revision or event["previous_hash"] != previous or digest(content) != claimed:
                fail("INVALID_JOURNAL: revision/hash chain mismatch; preserve source")
            if "delta" in event:
                if event["schema"] != SCHEMA or not records:
                    fail("INVALID_JOURNAL: delta requires a prior state and v2 reader")
                state = apply_delta(records[-1]["state"], event["delta"])
            else:
                state = event["state"]
            validate_state(state)
            if state["project"] != self.project or state["task"] != task or state["revision"] != revision:
                fail("INVALID_JOURNAL: task identity mismatch")
            records.append({**event, "state": state}); previous = claimed
        if not records:
            fail("INVALID_JOURNAL: empty journal")
        return records

    def load(self, task):
        return copy.deepcopy(self.history(task)[-1]["state"])

    def all_states(self):
        if not self.tasks.exists():
            return []
        states = []
        for path in sorted(self.tasks.iterdir()):
            reject_link(path)
            if path.is_dir():
                states.append(self.load(path.name))
        return states

    def projection(self, state):
        return {k: state[k] for k in ("task", "title", "revision", "status", "owner", "updated_at")} | {
            "workspace": state["snapshot"]["workspace"], "checkpoint": f"tasks/{state['task']}/CURRENT.md"}

    def rebuild_projections(self, task=None):
        states = self.all_states()
        for state in states:
            if task is None or state["task"] == task:
                atomic_write(self.task_dir(state["task"]) / "CURRENT.md", render(state).encode())
        index = {"schema": SCHEMA, "project": self.project, "tasks": [self.projection(s) for s in states]}
        atomic_write(self.directory / "INDEX.json", canonical(index) + b"\n")

    def owner_states(self):
        """Yield (project, state) for every task in this state root that still owns a workspace.

        A working directory is one physical resource while `project` is only a
        namespace, so workspace exclusivity must cross project boundaries; scoped
        to this project alone, a second project would report the same directory as
        free. A sibling journal that cannot be validated is surfaced instead of
        skipped, because ignoring it could present an owned directory as available.
        """
        for entry in sorted(self.root.iterdir()):
            if entry.is_symlink() or not entry.is_dir() or not (entry / "tasks").is_dir():
                continue
            try:
                identifier(entry.name)
            except HandoffError:
                continue  # project names are always identifiers, so this is not a project
            store = self if entry.name == self.project else Store(self.root, entry.name)
            try:
                states = store.all_states()
            except HandoffError as exc:
                fail(f"SIBLING_PROJECT_UNREADABLE: {entry.name}: {exc}")
            for state in states:
                if state["owner"] and state["status"] != "completed":
                    yield entry.name, state

    def ensure_available(self, workspace, excluding=None):
        # Called inside the shared state-root lock: scanning sibling projects
        # without the same lock would let two simultaneous claimers both pass.
        for project, state in self.owner_states():
            if (project, state["task"]) != excluding and state["snapshot"]["workspace"] == str(workspace):
                fail(f"WORKSPACE_CLAIMED: project {project} holds task {state['task']} on this workspace; release it before another writer claims it")

    def save(self, state, event_type, actor, expected):
        path = self.task_dir(state["task"])
        journal = path / "EVENTS.jsonl"
        history = self.history(state["task"]) if journal.exists() else []
        if expected != len(history):
            fail(f"STALE_REVISION: expected {expected}; current {len(history)}")
        if history:
            def meaningful(value):
                return {**{k: v for k, v in value.items() if k not in {"revision", "updated_at", "schema"}},
                        "references": value.get("references", [])}
            if meaningful(state) == meaningful(history[-1]["state"]):
                return copy.deepcopy(history[-1]["state"])
        state["schema"] = SCHEMA
        state.setdefault("references", [])
        state["revision"] = expected + 1
        state["updated_at"] = now()
        validate_state(state)
        self.outside_workspace(state["snapshot"]["workspace"])
        event = {"schema": SCHEMA, "revision": state["revision"],
                 "previous_hash": history[-1]["hash"] if history else "0" * 64,
                 "event": event_type, "actor": actor}
        if history:
            event["delta"] = delta_between(history[-1]["state"], state)
        else:
            event["state"] = state
        event["hash"] = digest(event)
        encoded = canonical(event) + b"\n"
        if len(encoded) + (journal.stat().st_size if journal.exists() else 0) > MAX_JSON:
            fail("SIZE_LIMIT: journal would exceed 32 MiB")
        path.mkdir(exist_ok=True, mode=0o700)
        reject_link(journal)
        # The fsynced event is the commit point. Both human CURRENT and INDEX are
        # projections, so interruption between their writes never loses a commit.
        with journal.open("ab") as stream:
            if os.name != "nt":
                os.chmod(journal, 0o600)
            stream.write(encoded); stream.flush(); os.fsync(stream.fileno())
        sync_dir(path)
        self.rebuild_projections(state["task"])
        return state


def check(store, state, workspace=None, include_snapshot=False):
    snap = state["snapshot"]
    destination = resolve_workspace(workspace or snap["workspace"])
    store.outside_workspace(destination)
    current = snapshot(destination, snap["scope"], snap["no_git"])
    changed = sorted(n for n in set(snap["files"]) | set(current["files"]) if snap["files"].get(n) != current["files"].get(n))
    pending = [k for k, v in state["operations"].items() if v["state"] in {"started", "unknown"}]
    projection = store.task_dir(state["task"]) / "CURRENT.md"
    reject_link(projection)
    projection_ok = projection.is_file() and projection.read_bytes() == render(state).encode()
    result = {"task": state["task"], "revision": state["revision"], "status": state["status"],
            "owner": state["owner"], "workspace_matches": current["workspace"] == snap["workspace"],
            "fingerprint_matches": current["fingerprint"] == snap["fingerprint"],
            "git_matches": current["git"] == snap["git"], "changed_files": changed,
            "pending_operations": pending, "recorded_processes": state["notes"]["processes"],
            "current_projection_matches": projection_ok, "live_fingerprint": current["fingerprint"]}
    if include_snapshot:
        result["snapshot"] = current
    return result


def resolve_reference(state_root, value, project=None):
    key = reference_key(value)
    if key.startswith("handoff://"):
        parsed = urlsplit(key)
        if project is not None and project != parsed.netloc:
            fail("REFERENCE_PROJECT_MISMATCH")
        store = Store(state_root, parsed.netloc)
        return store, store.load(parsed.path[1:])
    probe = Store(state_root, project or "InvoiceHub")
    if not probe.root.is_dir():
        fail("REFERENCE_NOT_REGISTERED: bind this link or provide a handoff:// task link")
    matches = []
    for directory in sorted(probe.root.iterdir()):
        if not directory.is_dir() or directory.is_symlink() or not (directory / "tasks").is_dir():
            continue
        if project is not None and directory.name != project:
            continue
        store = Store(probe.root, directory.name)
        for state in store.all_states():
            if key in {reference_key(ref) for ref in state.get("references", [])}:
                matches.append((store, state))
    if not matches:
        fail("REFERENCE_NOT_REGISTERED: no chat history is fetched; bind the link to a task first")
    if len(matches) != 1:
        choices = [task_reference(s["project"], s["task"]) for _, s in matches]
        fail("REFERENCE_AMBIGUOUS: choose an exact task: " + ", ".join(choices[:20]))
    return matches[0]


def require_owner(state, actor):
    if state["owner"] != actor:
        fail("NOT_TASK_OWNER: claim the task first; actor labels are cooperative, not credentials")


def output(value):
    print(canonical(value).decode())


def default_root():
    return os.environ.get("AGENT_HANDOFF_HOME") or str(Path.home() / ".agent-handoff")


def parser():
    p = argparse.ArgumentParser(description="Offline task handoff for any coding agent. No network, no execution of recorded commands.")
    p.add_argument("--version", action="version", version=VERSION)
    p.add_argument("--state-root", default=default_root(), help="private root OUTSIDE all workspaces; default AGENT_HANDOFF_HOME or ~/.agent-handoff")
    p.add_argument("--project", default=None, type=identifier)
    sub = p.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="register a workspace and create its first checkpoint")
    init.add_argument("--task", type=identifier, default=None)
    init.add_argument("--workspace", required=True)
    init.add_argument("--title", required=True)
    init.add_argument("--goal", required=True)
    init.add_argument("--actor", required=True)
    init.add_argument("--ref", action="append", default=[], help="thread link/ID to bind; repeatable")
    init.add_argument("--acceptance", action="append", help="observable acceptance criterion; repeatable")
    init.add_argument("--next-step", action="append", help="concrete next action; repeatable")
    init.add_argument("--scope", nargs="*", default=[])
    init.add_argument("--no-git", action="store_true")
    init.add_argument("--input", type=Path, help="complete notes JSON; overrides --goal")
    listing = sub.add_parser("list", help="list tasks from validated journals")
    listing.add_argument("--limit", type=int, default=20)
    listing.add_argument("--offset", type=int, default=0)
    listing.add_argument("--all", action="store_true")
    resolver = sub.add_parser("resolve", help="resolve a registered thread link/ID or handoff:// link")
    resolver.add_argument("--ref", required=True)
    for name in ("show", "check", "resume", "template", "checkpoint", "claim", "release", "event", "repair", "bind", "ticket"):
        cmd = sub.add_parser(name)
        if name == "bind":
            cmd.add_argument("--task", required=True, type=identifier)
            cmd.add_argument("--ref", required=True)
        else:
            target = cmd.add_mutually_exclusive_group(required=True)
            target.add_argument("--task", type=identifier)
            target.add_argument("--ref")
        if name in {"checkpoint", "claim", "release", "event", "bind"}:
            cmd.add_argument("--actor", required=True)
            cmd.add_argument("--expect-revision", required=True, type=int)
        if name in {"resume", "show"}:
            cmd.add_argument("--full", action="store_true", help="explicitly read complete state")
            cmd.add_argument("--max-chars", type=int, default=BRIEF_CHARS)
        if name == "show":
            cmd.add_argument("--section", choices=sorted(NOTE_FIELDS | {"snapshot", "operations", "references"}))
        if name == "resume":
            cmd.add_argument("--verify", action="store_true", help="also hash and compare live files; default is read-only summary")
        if name == "check":
            cmd.add_argument("--full", action="store_true", help="include all changed paths and operations")
        if name in {"check", "resume", "claim"}:
            cmd.add_argument("--workspace")
        if name in {"template", "checkpoint"}:
            cmd.add_argument("--input" if name == "checkpoint" else "--output", type=Path, required=name == "checkpoint")
        if name == "checkpoint":
            cmd.add_argument("--status", choices=sorted(STATUSES), default="active")
            cmd.add_argument("--processes-checked", action="store_true")
        if name == "claim":
            cmd.add_argument("--previous-writer-stopped", action="store_true")
            cmd.add_argument("--accept-drift", action="store_true")
        if name == "release":
            cmd.add_argument("--next")
            cmd.add_argument("--input", type=Path, help="save notes and release in one write")
            cmd.add_argument("--processes-checked", action="store_true")
        if name == "event":
            cmd.add_argument("--operation", required=True, type=identifier)
            cmd.add_argument("--state", required=True, choices=["started", "confirmed", "failed_confirmed", "unknown"])
            cmd.add_argument("--detail", required=True)
        if name == "repair":
            cmd.add_argument("--discard-incomplete-tail", action="store_true")
    return p


def run(args):
    if args.command not in {"init", "bind"} and getattr(args, "ref", None):
        store, selected = resolve_reference(args.state_root, args.ref, args.project)
        args.project, args.task = selected["project"], selected["task"]
    else:
        args.project = args.project or "InvoiceHub"
        store = Store(args.state_root, args.project)
    if args.command == "resolve":
        output(store.projection(selected) | {"task_ref": task_reference(args.project, args.task)})
        return 0
    if args.command == "init":
        workspace = resolve_workspace(args.workspace)
        store.outside_workspace(workspace)
        snap = snapshot(workspace, args.scope, args.no_git)
        notes = read_json(args.input) if args.input else notes_template(args.goal)
        if not args.input:
            if args.acceptance:
                notes["acceptance_criteria"] = args.acceptance
            if args.next_step:
                notes["next_steps"] = args.next_step
        validate_notes(notes)
        state = {"schema": SCHEMA, "project": args.project, "task": args.task or uuid.uuid4().hex,
                 "title": nonempty(args.title, "title"), "revision": 1, "status": "active",
                 "owner": nonempty(args.actor, "actor"), "updated_at": now(), "notes": notes,
                 "snapshot": snap, "operations": {}, "references": args.ref}
        store.prepare()
        with state_root_lock(store.root):
            if store.task_dir(state["task"]).exists():
                fail("TASK_EXISTS: choose another task ID")
            store.ensure_available(workspace)
            output(store.projection(store.save(state, "init", args.actor, 0)))
        return 0
    if not store.directory.is_dir():
        fail("PROJECT_NOT_FOUND: run init first")
    if args.command == "list":
        if not 1 <= args.limit <= 200 or args.offset < 0:
            fail("INVALID_PAGE: limit 1..200 and nonnegative offset required")
        states = store.all_states()
        end = len(states) if args.all else min(args.offset + args.limit, len(states))
        output({"schema": SCHEMA, "project": args.project, "total": len(states),
                "next_offset": end if end < len(states) else None,
                "tasks": [store.projection(s) for s in states[args.offset:end]]})
        return 0
    if args.command == "repair":
        with state_root_lock(store.root):
            path = store.task_dir(args.task) / "EVENTS.jsonl"
            reject_link(path)
            if args.discard_incomplete_tail:
                raw = path.read_bytes()
                if not raw.endswith(b"\n"):
                    last = raw.rfind(b"\n")
                    if last < 0:
                        fail("NO_VALID_COMMIT: no complete event to recover")
                    recovered = store.decode_history(args.task, raw[:last + 1])
                    store.outside_workspace(recovered[-1]["state"]["snapshot"]["workspace"])
                    backup = path.with_name(f"EVENTS.interrupted-{uuid.uuid4().hex}.bak")
                    atomic_write(backup, raw)
                    atomic_write(path, raw[:last + 1])
            repaired = store.history(args.task)
            store.outside_workspace(repaired[-1]["state"]["snapshot"]["workspace"])
            store.rebuild_projections(args.task)
        output({"repaired": True, "task": args.task})
        return 0
    state = store.load(args.task)
    if args.command == "ticket":
        ref = task_reference(state["project"], state["task"])
        output({"handoff": ref, "state_root": str(store.root)})
        return 0
    if args.command == "show":
        if args.section:
            value = state["notes"][args.section] if args.section in NOTE_FIELDS else state.get(args.section, [])
            output({"task_ref": task_reference(state["project"], state["task"]), "revision": state["revision"], "section": args.section, "value": value})
        else:
            output(state if args.full else brief(state, args.max_chars))
        return 0
    if args.command in {"check", "resume"}:
        if args.command == "resume" and not args.verify:
            output(state if args.full else brief(state, args.max_chars))
            return 0
        result = check(store, state, args.workspace)
        if args.command == "check":
            result["changed_files_count"] = len(result["changed_files"])
            result["pending_operations_count"] = len(result["pending_operations"])
            result["recorded_processes_count"] = len(result["recorded_processes"])
            if not args.full:
                result["changed_files"] = result["changed_files"][:20]
                result["pending_operations"] = result["pending_operations"][:20]
                result["recorded_processes"] = [line[:320] + ("…" if len(line) > 320 else "") for line in result["recorded_processes"][:5]]
                result["details"] = "check --full for complete paths, operations and process notes"
            output(result)
        else:
            packet = {"state": state} if args.full else brief(state, args.max_chars)
            packet["live_check"] = {key: result[key] for key in ("fingerprint_matches", "current_projection_matches", "git_matches")}
            output(packet)
        return 0 if result["fingerprint_matches"] and result["current_projection_matches"] and not result["pending_operations"] else 3
    if args.command == "template":
        store.outside_workspace(state["snapshot"]["workspace"])
        data = json.dumps(state["notes"], ensure_ascii=False, indent=2) + "\n"
        if args.output:
            destination = args.output.expanduser().resolve()
            if not inside(destination, store.directory):
                fail("PRIVATE_OUTPUT_REQUIRED: write the template inside this private project directory")
            if destination.exists():
                fail("OUTPUT_EXISTS: choose a new template name")
            atomic_write(destination, data.encode())
            output({"output": str(destination), "expect_revision": state["revision"]})
        else:
            print(data)
        return 0
    nonempty(args.actor, "actor")
    with state_root_lock(store.root):
        state = store.load(args.task)
        if state["revision"] != args.expect_revision:
            fail(f"STALE_REVISION: current {state['revision']}")
        if state["status"] == "completed" and args.command != "bind":
            fail("TASK_COMPLETED: start a linked task instead of reopening completed work")
        if args.command == "claim":
            if not args.previous_writer_stopped:
                fail("WRITER_CHECK_REQUIRED: inspect previous writers, then --previous-writer-stopped")
            result = check(store, state, args.workspace, include_snapshot=True)
            if not result["fingerprint_matches"] and not args.accept_drift:
                fail("WORKSPACE_DRIFT: inspect check output; use --accept-drift only after reconciliation")
            workspace = resolve_workspace(args.workspace or state["snapshot"]["workspace"])
            store.ensure_available(workspace, (store.project, args.task))
            state["snapshot"] = result["snapshot"]
            state["owner"] = args.actor; state["status"] = "active"
        elif args.command == "bind":
            if state["owner"] is not None:
                require_owner(state, args.actor)
            key = reference_key(args.ref)
            if key.startswith("handoff://"):
                fail("INVALID_REFERENCE: task links already resolve directly; bind an external thread link/ID")
            refs = state.setdefault("references", [])
            if key not in {reference_key(ref) for ref in refs}:
                refs.append(args.ref.strip())
        else:
            require_owner(state, args.actor)
            if args.command == "checkpoint":
                notes = read_json(args.input); validate_notes(notes)
                state["notes"] = notes; state["status"] = args.status
                state["snapshot"] = snapshot(state["snapshot"]["workspace"], state["snapshot"]["scope"], state["snapshot"]["no_git"])
                if args.status in {"ready_for_handoff", "completed"}:
                    if not args.processes_checked:
                        fail("PROCESS_CHECK_REQUIRED: inspect recorded processes before releasing ownership")
                    if any(op["state"] in {"started", "unknown"} for op in state["operations"].values()) and args.status == "completed":
                        fail("UNRESOLVED_OPERATIONS: completed status requires confirmed outcomes")
                    state["owner"] = None
            elif args.command == "release":
                if not args.processes_checked:
                    fail("PROCESS_CHECK_REQUIRED: inspect recorded processes before release")
                if args.input:
                    notes = read_json(args.input); validate_notes(notes)
                    state["notes"] = notes
                if args.next:
                    state["notes"]["next_steps"] = [nonempty(args.next, "next")]
                if not args.input and not args.next:
                    fail("NEXT_STEP_REQUIRED: provide --next or --input notes")
                state["snapshot"] = snapshot(state["snapshot"]["workspace"], state["snapshot"]["scope"], state["snapshot"]["no_git"])
                state["status"] = "ready_for_handoff"; state["owner"] = None
            elif args.command == "event":
                existing = state["operations"].get(args.operation)
                if existing and existing["state"] in {"confirmed", "failed_confirmed"}:
                    fail("OPERATION_FINAL: terminal outcome cannot be downgraded or replayed")
                if existing is None and args.state != "started":
                    fail("OPERATION_NOT_STARTED: record intention before the external action")
                if existing and args.state == "started":
                    fail("OPERATION_EXISTS: reconcile the original operation before any retry")
                state["operations"][args.operation] = {"state": args.state, "detail": nonempty(args.detail, "detail"), "updated_at": now()}
        output(store.projection(store.save(state, args.command, args.actor, args.expect_revision)))
    return 0


def menu():
    print("Agent Handoff — 离线任务接力\n1. 创建任务  2. 列出任务  3. 查看接手说明\n")
    choice = input("选择 [1/2/3]: ").strip()
    state_root = input(f"私有目录 [{default_root()}]: ").strip() or default_root()
    project = input("项目名 [InvoiceHub]: ").strip() or "InvoiceHub"
    argv = ["--state-root", state_root, "--project", project]
    if choice == "1":
        workspace = input("工作目录: ").strip()
        argv += ["init", "--workspace", workspace, "--title", input("任务名称: ").strip(),
                 "--goal", input("完成目标: ").strip(), "--actor", input("执行者名称: ").strip(),
                 "--acceptance", input("怎样算完成: ").strip(), "--next-step", input("接下来第一个具体动作: ").strip()]
        if git(resolve_workspace(workspace), "rev-parse", "--show-toplevel", optional=True) is None:
            answer = input("无法读取 Git 状态，按普通文件任务处理（仅核对选定文件）[y/N]: ").strip().lower()
            if answer not in {"y", "yes"}:
                fail("未创建任务；请准备 Git 或选择普通文件模式")
            argv += ["--no-git", "--scope", input("要核对的相对文件或目录: ").strip()]
    elif choice == "2":
        argv += ["list"]
    elif choice == "3":
        ref = input("任务 ID、线程链接/UUID 或 handoff://链接: ").strip()
        is_ref = "://" in ref or reference_key(ref).startswith("id:")
        argv += ["resume", "--ref" if is_ref else "--task", ref]
    else:
        fail("请选择 1、2 或 3")
    return run(parser().parse_args(argv))


def main(argv=None):
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        if argv is None and len(sys.argv) == 1 and sys.stdin.isatty():
            code = menu()
            input("\n按回车关闭…")
            return code
        return run(parser().parse_args(argv))
    except (HandoffError, OSError, ValueError, TypeError, KeyError, subprocess.TimeoutExpired) as exc:
        output({"ok": False, "error": str(exc), "retry_automatically": False,
                "recovery": "Inspect the last journal revision before retrying a write."})
        return 2
    except KeyboardInterrupt:
        print("Interrupted; verify the last journal revision before retrying.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
