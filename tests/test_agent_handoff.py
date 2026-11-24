"""Behavioral checks for private, resumable, vendor-neutral checkpoints."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/dev/agent_handoff.py"
SPEC = importlib.util.spec_from_file_location("agent_handoff", SCRIPT)
handoff = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(handoff)


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="handoff-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.workspace = self.base / "workspace"
        self.workspace.mkdir()
        (self.workspace / "example.txt").write_text("synthetic source\n", encoding="utf-8")
        self.private = self.base / "private"
        self.prefix = ["--state-root", str(self.private), "--project", "Example"]
        self.store = handoff.Store(self.private, "Example")

    def cli(self, *args, code=0):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            actual = handoff.main(self.prefix + list(args))
        self.assertEqual(actual, code, output.getvalue())
        return output.getvalue()

    def initialize(self):
        self.cli("init", "--task", "work", "--workspace", str(self.workspace),
                 "--title", "Task line", "--goal", "Finish a synthetic task", "--actor", "agent-a",
                 "--no-git", "--scope", "example.txt")

    def event(self, state, revision, operation="export", code=0):
        return self.cli("event", "--task", "work", "--actor", "agent-a",
                        "--expect-revision", str(revision), "--operation", operation,
                        "--state", state, "--detail", "synthetic evidence", code=code)

    def test_different_agent_can_resume_without_chat_or_git(self):
        self.initialize()
        self.cli("release", "--task", "work", "--actor", "agent-a", "--expect-revision", "1",
                 "--processes-checked", "--next", "Read example.txt and add one documented line")
        text = self.cli("resume", "--task", "work")
        self.assertIn("Finish a synthetic task", text)
        self.assertIn("Read example.txt and add one documented line", text)
        self.cli("claim", "--task", "work", "--actor", "unrelated-agent",
                 "--expect-revision", "2", "--previous-writer-stopped")
        self.assertEqual(self.store.load("work")["owner"], "unrelated-agent")

    def test_stale_revision_and_non_owner_cannot_overwrite(self):
        self.initialize()
        self.event("started", 1)
        before = (self.store.task_dir("work") / "EVENTS.jsonl").read_bytes()
        self.event("unknown", 1, code=2)
        self.cli("release", "--task", "work", "--actor", "agent-b", "--expect-revision", "2",
                 "--next", "Continue", "--processes-checked", code=2)
        self.assertEqual(before, (self.store.task_dir("work") / "EVENTS.jsonl").read_bytes())

    def test_unknown_operation_blocks_clean_check_and_cannot_be_restarted(self):
        self.initialize()
        self.event("started", 1)
        self.event("unknown", 2)
        result = json.loads(self.cli("check", "--task", "work", code=3))
        self.assertEqual(result["pending_operations"], ["export"])
        self.event("started", 3, code=2)
        self.event("confirmed", 3)
        self.event("unknown", 4, code=2)
        self.cli("check", "--task", "work")

    def test_file_drift_is_reported_and_requires_explicit_reconciliation(self):
        self.initialize()
        (self.workspace / "example.txt").write_text("changed\n", encoding="utf-8")
        result = json.loads(self.cli("check", "--task", "work", code=3))
        self.assertEqual(result["changed_files"], ["example.txt"])
        self.cli("claim", "--task", "work", "--actor", "agent-b", "--expect-revision", "1",
                 "--previous-writer-stopped", code=2)
        self.cli("claim", "--task", "work", "--actor", "agent-b", "--expect-revision", "1",
                 "--previous-writer-stopped", "--accept-drift")
        self.cli("check", "--task", "work")

    def test_snapshot_does_not_store_source_contents_or_follow_symlinks(self):
        secret = self.base / "outside.txt"
        secret.write_text("PRIVATE-CONTENT-NOT-IN-CHECKPOINT", encoding="utf-8")
        try:
            (self.workspace / "link").symlink_to(secret)
        except OSError:
            self.skipTest("symlink creation unavailable")
        snap = handoff.snapshot(self.workspace, ["link"], no_git=True)
        self.assertEqual(snap["files"]["link"]["kind"], "symlink")
        self.assertNotIn(secret.read_text(encoding="utf-8"), json.dumps(snap))

    def test_private_state_cannot_be_inside_workspace_or_another_git_repository(self):
        self.prefix = ["--state-root", str(self.workspace / "ignored"), "--project", "Example"]
        self.cli("init", "--task", "work", "--workspace", str(self.workspace),
                 "--title", "Test", "--goal", "Test", "--actor", "agent-a",
                 "--no-git", "--scope", "example.txt", code=2)
        self.assertFalse((self.workspace / "ignored").exists())
        if shutil.which("git"):
            other = self.base / "other-public"
            subprocess.run(["git", "init", "-q", str(other)], check=True)
            with self.assertRaisesRegex(handoff.HandoffError, "INSIDE_GIT"):
                handoff.Store(other / "ignored", "Example")

    def test_same_workspace_cannot_have_two_claimed_task_lines(self):
        self.initialize()
        self.cli("init", "--task", "second", "--workspace", str(self.workspace),
                 "--title", "Second", "--goal", "Test", "--actor", "agent-b",
                 "--no-git", "--scope", "example.txt", code=2)

    def test_projections_recover_after_interrupted_commit(self):
        self.initialize()
        with mock.patch.object(handoff.Store, "rebuild_projections", side_effect=OSError("synthetic interruption")):
            self.event("started", 1, code=2)
        self.assertEqual(self.store.load("work")["revision"], 2)
        result = json.loads(self.cli("check", "--task", "work", code=3))
        self.assertFalse(result["current_projection_matches"])
        self.cli("repair", "--task", "work")
        self.assertEqual(json.loads(self.cli("list"))["tasks"][0]["revision"], 2)
        self.assertIn("Revision: 2", (self.store.task_dir("work") / "CURRENT.md").read_text(encoding="utf-8"))

    def test_truncated_tail_requires_repair_and_preserves_exact_backup(self):
        self.initialize()
        journal = self.store.task_dir("work") / "EVENTS.jsonl"
        original = journal.read_bytes()
        broken = original + b'{"incomplete":'
        journal.write_bytes(broken)
        self.cli("show", "--task", "work", code=2)
        self.cli("repair", "--task", "work", "--discard-incomplete-tail")
        self.assertEqual(journal.read_bytes(), original)
        backups = list(journal.parent.glob("*.bak"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), broken)

    def test_invalid_complete_record_is_never_discarded_by_tail_repair(self):
        self.initialize()
        journal = self.store.task_dir("work") / "EVENTS.jsonl"
        broken = journal.read_bytes() + b'{}\n{"incomplete":'
        journal.write_bytes(broken)
        self.cli("repair", "--task", "work", "--discard-incomplete-tail", code=2)
        self.assertEqual(journal.read_bytes(), broken)

    def test_bad_notes_do_not_replace_valid_history(self):
        self.initialize()
        candidate = self.base / "candidate.json"
        candidate.write_text('{"goal":"oops","goal":"duplicate"}', encoding="utf-8")
        self.cli("checkpoint", "--task", "work", "--actor", "agent-a", "--expect-revision", "1",
                 "--input", str(candidate), code=2)
        self.assertEqual(self.store.load("work")["revision"], 1)

    def test_checkpoint_requires_process_check_before_completing(self):
        self.initialize()
        candidate = self.private / "Example" / "candidate.json"
        self.cli("template", "--task", "work", "--output", str(candidate))
        self.cli("checkpoint", "--task", "work", "--actor", "agent-a", "--expect-revision", "1",
                 "--input", str(candidate), "--status", "completed", code=2)
        self.cli("checkpoint", "--task", "work", "--actor", "agent-a", "--expect-revision", "1",
                 "--input", str(candidate), "--status", "completed", "--processes-checked")
        self.assertIsNone(self.store.load("work")["owner"])

    def test_concurrent_writers_only_one_commits_expected_revision(self):
        self.initialize()
        common = [sys.executable, str(SCRIPT), *self.prefix, "event", "--task", "work",
                  "--actor", "agent-a", "--expect-revision", "1", "--state", "started", "--detail", "synthetic"]
        workers = [subprocess.Popen(common + ["--operation", op], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                   for op in ("one", "two")]
        for worker in workers:
            worker.communicate(timeout=15)
        self.assertEqual(sorted(w.returncode for w in workers), [0, 2])
        self.assertEqual(self.store.load("work")["revision"], 2)

    def test_template_output_cannot_write_into_public_workspace(self):
        self.initialize()
        self.cli("template", "--task", "work", "--output", str(self.workspace / "leak.json"), code=2)
        self.assertFalse((self.workspace / "leak.json").exists())

    def test_link_uuid_and_task_ticket_resolve_without_chat_access(self):
        self.initialize()
        thread_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        self.cli("bind", "--task", "work", "--ref", f"thread://{thread_id}?hostId=local",
                 "--actor", "agent-a", "--expect-revision", "1")
        for ref in (thread_id, f"codex://threads/{thread_id}", "handoff://Example/work"):
            resolved = json.loads(self.cli("resolve", "--ref", ref))
            self.assertEqual(resolved["task"], "work")
        ticket = json.loads(self.cli("ticket", "--task", "work"))
        self.assertEqual(ticket, {"handoff": "handoff://Example/work", "state_root": str(self.private.resolve())})
        self.assertEqual(json.loads(self.cli("resume", "--ref", thread_id))["task_ref"], ticket["handoff"])
        self.cli("resolve", "--ref", "unregistered-thread", code=2)

    def test_ambiguous_thread_reference_never_picks_the_latest_task(self):
        self.initialize()
        self.cli("bind", "--task", "work", "--ref", "shared-thread", "--actor", "agent-a", "--expect-revision", "1")
        self.cli("release", "--task", "work", "--actor", "agent-a", "--expect-revision", "2",
                 "--processes-checked", "--next", "Continue")
        self.cli("init", "--task", "second", "--workspace", str(self.workspace), "--title", "Second",
                 "--goal", "Second task", "--actor", "agent-b", "--no-git", "--scope", "example.txt", "--ref", "shared-thread")
        text = self.cli("resolve", "--ref", "shared-thread", code=2)
        self.assertIn("REFERENCE_AMBIGUOUS", text)
        self.assertEqual(json.loads(self.cli("resolve", "--ref", "handoff://Example/second"))["task"], "second")

    def test_unchanged_checkpoint_does_not_write_or_increment_revision(self):
        self.initialize()
        notes = self.store.load("work")["notes"]
        candidate = self.private / "Example/notes.json"
        candidate.write_text(json.dumps(notes), encoding="utf-8")
        paths = [self.store.task_dir("work") / name for name in ("CURRENT.md", "EVENTS.jsonl")]
        paths += [self.private / "Example/INDEX.json"]
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths}
        with mock.patch.object(handoff, "atomic_write", side_effect=AssertionError("unexpected write")):
            result = json.loads(self.cli("checkpoint", "--task", "work", "--actor", "agent-a",
                                         "--expect-revision", "1", "--input", str(candidate)))
        self.assertEqual(result["revision"], 1)
        self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths})

    def test_default_reads_neither_write_nor_rehash_workspace(self):
        self.initialize()
        with mock.patch.object(handoff, "atomic_write", side_effect=AssertionError("read wrote data")), \
             mock.patch.object(handoff, "snapshot", side_effect=AssertionError("read rehashed source")):
            for command in ("show", "resume", "ticket", "template"):
                self.cli(command, "--task", "work")
            self.cli("list")
            self.cli("resolve", "--ref", "handoff://Example/work")
        self.assertEqual(json.loads(self.cli("resume", "--task", "work"))["live_check"], "not_run")

    def test_brief_budget_and_expansion_preserve_full_critical_notes(self):
        self.initialize()
        state = self.store.load("work")
        state["notes"]["constraints"] = ["constraint " + str(i) + ":" + "很重要" * 300 for i in range(12)]
        candidate = self.private / "Example/notes.json"
        candidate.write_text(json.dumps(state["notes"]), encoding="utf-8")
        self.cli("checkpoint", "--task", "work", "--actor", "agent-a", "--expect-revision", "1", "--input", str(candidate))
        text = self.cli("resume", "--task", "work", "--max-chars", "2000")
        self.assertLessEqual(len(text.rstrip()), 2000)
        packet = json.loads(text)
        self.assertTrue(packet["expand_before_action"])
        self.assertIn("constraints", packet["omitted_fields"])
        self.assertNotIn("files", packet)
        full = json.loads(self.cli("show", "--task", "work", "--section", "constraints"))
        self.assertEqual(full["value"], state["notes"]["constraints"])
        self.assertEqual(json.loads(self.cli("show", "--task", "work", "--full"))["notes"], state["notes"])

    def test_v2_events_are_small_deltas_and_reconstruct_the_same_state(self):
        self.initialize()
        journal = self.store.task_dir("work") / "EVENTS.jsonl"
        first = journal.read_bytes()
        self.event("started", 1)
        lines = journal.read_bytes().splitlines()
        second = json.loads(lines[-1])
        self.assertIn("delta", second)
        self.assertNotIn("state", second)
        self.assertNotIn(b"acceptance_criteria", lines[-1])
        self.assertLess(len(lines[-1]), len(first))
        self.assertEqual(self.store.load("work")["operations"]["export"]["state"], "started")

    def test_legacy_full_events_remain_unchanged_when_v2_is_appended(self):
        self.initialize()
        journal = self.store.task_dir("work") / "EVENTS.jsonl"
        legacy = json.loads(journal.read_bytes())
        legacy["schema"] = legacy["state"]["schema"] = handoff.LEGACY_SCHEMA
        legacy["state"].pop("references")
        legacy["hash"] = handoff.digest({k: v for k, v in legacy.items() if k != "hash"})
        raw = handoff.canonical(legacy) + b"\n"
        journal.write_bytes(raw)
        self.assertEqual(self.store.load("work")["schema"], handoff.LEGACY_SCHEMA)
        self.event("started", 1)
        self.assertTrue(journal.read_bytes().startswith(raw))
        self.assertEqual(self.store.load("work")["schema"], handoff.SCHEMA)

    def test_one_task_update_preserves_other_current_files(self):
        self.initialize()
        other = self.base / "other"
        other.mkdir(); (other / "example.txt").write_text("another task", encoding="utf-8")
        self.cli("init", "--task", "second", "--workspace", str(other), "--title", "Second", "--goal", "Other",
                 "--actor", "agent-b", "--no-git", "--scope", "example.txt")
        other_current = self.store.task_dir("second") / "CURRENT.md"
        before = (other_current.read_bytes(), other_current.stat().st_mtime_ns)
        real_write = handoff.atomic_write
        with mock.patch.object(handoff, "atomic_write", wraps=real_write) as writes:
            self.event("started", 1)
        self.assertNotIn(other_current, [call.args[0] for call in writes.call_args_list])
        self.assertEqual(before, (other_current.read_bytes(), other_current.stat().st_mtime_ns))

    def test_claim_hashes_live_files_once_and_release_can_save_notes_once(self):
        self.initialize()
        candidate = self.private / "Example/notes.json"
        notes = self.store.load("work")["notes"]
        notes["next_steps"] = ["Continue the precise task"]
        candidate.write_text(json.dumps(notes), encoding="utf-8")
        self.cli("release", "--task", "work", "--actor", "agent-a", "--expect-revision", "1",
                 "--input", str(candidate), "--processes-checked")
        self.assertEqual(self.store.load("work")["revision"], 2)
        with mock.patch.object(handoff, "snapshot", wraps=handoff.snapshot) as captures:
            self.cli("claim", "--task", "work", "--actor", "agent-b", "--expect-revision", "2", "--previous-writer-stopped")
        self.assertEqual(captures.call_count, 1)

    def test_invalid_delta_is_preserved_and_repair_cannot_clear_it(self):
        self.initialize(); self.event("started", 1)
        journal = self.store.task_dir("work") / "EVENTS.jsonl"
        lines = journal.read_bytes().splitlines()
        bad = json.loads(lines[-1])
        bad["delta"]["drop"] = ["missing-key"]
        bad["hash"] = handoff.digest({k: v for k, v in bad.items() if k != "hash"})
        raw = lines[0] + b"\n" + handoff.canonical(bad) + b"\n"
        journal.write_bytes(raw)
        self.cli("repair", "--task", "work", code=2)
        self.assertEqual(journal.read_bytes(), raw)

    def test_interactive_menu_creates_a_complete_non_git_checkpoint(self):
        answers = ["1", str(self.private), "Example", str(self.workspace), "Draft review",
                   "Review synthetic draft", "Human", "Two reviewed lines", "Read example.txt", "y", "example.txt"]
        with mock.patch("builtins.input", side_effect=answers), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(handoff.menu(), 0)
        state = self.store.all_states()[0]
        self.assertEqual(state["notes"]["acceptance_criteria"], ["Two reviewed lines"])
        self.assertEqual(state["notes"]["next_steps"], ["Read example.txt"])
        self.assertTrue(state["snapshot"]["no_git"])

    def test_other_project_init_is_serialized_by_the_shared_root_lock(self):
        self.initialize()
        second = self.base / "second-workspace"
        second.mkdir()
        (second / "example.txt").write_text("synthetic\n", encoding="utf-8")
        command = [sys.executable, str(SCRIPT), "--state-root", str(self.private),
                   "--project", "Another", "init", "--task", "second", "--workspace", str(second),
                   "--title", "Second", "--goal", "Check root mutex", "--actor", "agent-b",
                   "--no-git", "--scope", "example.txt"]
        with handoff.state_root_lock(self.private):
            worker = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                with self.assertRaises(subprocess.TimeoutExpired):
                    worker.communicate(timeout=0.5)
            finally:
                if worker.poll() is not None:
                    self.fail("a sibling project bypassed the state-root lock")
        stdout, stderr = worker.communicate(timeout=10)
        self.assertEqual(worker.returncode, 0, (stdout, stderr))

    def test_symlinked_journal_is_rejected(self):
        self.initialize()
        journal = self.store.task_dir("work") / "EVENTS.jsonl"
        outside = self.base / "original.jsonl"
        journal.rename(outside)
        try:
            journal.symlink_to(outside)
        except OSError:
            self.skipTest("symlink creation unavailable")
        self.cli("show", "--task", "work", code=2)
        self.assertTrue(outside.is_file())

    def rewrite_first_event(self, mutate):
        """Rebuild event 1 with a recomputed hash, so only `mutate` decides the outcome."""
        journal = self.store.task_dir("work") / "EVENTS.jsonl"
        lines = journal.read_bytes().splitlines(keepends=True)
        event = json.loads(lines[0].decode())
        mutate(event)
        event.pop("hash", None)
        event["hash"] = handoff.digest(event)
        lines[0] = handoff.canonical(event) + b"\n"
        journal.write_bytes(b"".join(lines))
        return journal, b"".join(lines)

    def test_tampered_event_payload_fails_the_hash_chain_and_survives_repair(self):
        self.initialize()
        journal = self.store.task_dir("work") / "EVENTS.jsonl"
        lines = journal.read_bytes().splitlines(keepends=True)
        event = json.loads(lines[0].decode())
        event["state"]["notes"]["goal"] = "quietly rewritten outside the tool"
        lines[0] = handoff.canonical(event) + b"\n"
        journal.write_bytes(b"".join(lines))
        self.assertIn("INVALID_JOURNAL", self.cli("show", "--task", "work", code=2))
        self.cli("repair", "--task", "work", "--discard-incomplete-tail", code=2)
        self.assertEqual(journal.read_bytes(), b"".join(lines))
        self.assertEqual(list(journal.parent.glob("*.bak")), [])

    def test_future_event_schema_is_rejected_however_valid_the_chain_is(self):
        self.initialize()
        journal, rewritten = self.rewrite_first_event(
            lambda event: event.__setitem__("schema", "agent-handoff/v999"))
        self.assertIn("INVALID_JOURNAL", self.cli("show", "--task", "work", code=2))
        self.cli("repair", "--task", "work", "--discard-incomplete-tail", code=2)
        self.assertEqual(journal.read_bytes(), rewritten)

    def test_future_state_schema_never_rewrites_projections_during_repair(self):
        self.initialize()
        projection = self.store.task_dir("work") / "CURRENT.md"
        before = projection.read_bytes()
        self.rewrite_first_event(
            lambda event: event["state"].__setitem__("schema", "agent-handoff/v999"))
        self.assertIn("INVALID_SCHEMA", self.cli("repair", "--task", "work", code=2))
        self.assertEqual(projection.read_bytes(), before)

    def test_journal_without_one_complete_event_is_never_repaired_into_an_empty_task(self):
        self.initialize()
        journal = self.store.task_dir("work") / "EVENTS.jsonl"
        journal.write_bytes(b'{"incomplete":')
        self.assertIn("NO_VALID_COMMIT",
                      self.cli("repair", "--task", "work", "--discard-incomplete-tail", code=2))
        self.assertEqual(journal.read_bytes(), b'{"incomplete":')
        self.assertEqual(list(journal.parent.glob("*.bak")), [])

    def other_project(self, *args, code=0):
        """Run the same tool under a second project name sharing one state root."""
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            actual = handoff.main(["--state-root", str(self.private), "--project", "Other", *args])
        self.assertEqual(actual, code, output.getvalue())
        return output.getvalue()

    def register_other_project(self, workspace, code=0):
        return self.other_project("init", "--task", "work", "--workspace", str(workspace),
                                  "--title", "Other line", "--goal", "Finish another synthetic task",
                                  "--actor", "agent-b", "--no-git", "--scope", "example.txt", code=code)

    def test_workspace_exclusivity_crosses_project_boundaries(self):
        self.initialize()
        message = self.register_other_project(self.workspace, code=2)
        self.assertIn("WORKSPACE_CLAIMED", message)
        self.assertFalse((self.private / "Other" / "tasks" / "work").exists())

    def test_workspace_freed_by_release_is_claimable_by_another_project(self):
        self.initialize()
        self.cli("release", "--task", "work", "--actor", "agent-a", "--expect-revision", "1",
                 "--processes-checked", "--next", "Continue later")
        self.register_other_project(self.workspace)
        self.assertTrue((self.private / "Other" / "tasks" / "work" / "CURRENT.md").is_file())
        message = self.cli("claim", "--task", "work", "--actor", "agent-a",
                           "--expect-revision", "2", "--previous-writer-stopped", code=2)
        self.assertIn("WORKSPACE_CLAIMED", message)

    def test_sibling_projects_on_separate_workspaces_remain_independent(self):
        self.initialize()
        second = self.base / "workspace-two"
        second.mkdir()
        (second / "example.txt").write_text("synthetic source\n", encoding="utf-8")
        self.register_other_project(second)
        self.cli("check", "--task", "work")


class GitCheckpointTests(unittest.TestCase):
    """The Git path binds HEAD, the index and the work tree; --no-git never claims them.

    Every test in HandoffTests runs with --no-git, so without this class the Git
    collector could regress to a constant or empty identity unnoticed.
    """

    def setUp(self):
        if not shutil.which("git"):
            self.skipTest("Git unavailable; the plain-file path is covered by HandoffTests")
        self.temp = tempfile.TemporaryDirectory(prefix="handoff-git-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.workspace = self.base / "repo"
        self.workspace.mkdir()
        self.git("init", "-q")
        self.git("symbolic-ref", "HEAD", "refs/heads/synthetic-main")
        (self.workspace / "tracked.txt").write_text("one\n", encoding="utf-8")
        (self.workspace / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
        (self.workspace / "ignored.txt").write_text("synthetic ignored\n", encoding="utf-8")
        self.git("add", "tracked.txt", ".gitignore")
        self.git("commit", "-q", "-m", "synthetic baseline")
        self.private = self.base / "private"
        self.prefix = ["--state-root", str(self.private), "--project", "Example"]
        self.store = handoff.Store(self.private, "Example")

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.workspace), "-c", "user.email=synthetic@example.invalid",
                        "-c", "user.name=Synthetic", "-c", "commit.gpgsign=false", *args],
                       check=True, capture_output=True, env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))

    def cli(self, *args, code=0):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            actual = handoff.main(self.prefix + list(args))
        self.assertEqual(actual, code, output.getvalue())
        return output.getvalue()

    def initialize(self):
        self.cli("init", "--task", "work", "--workspace", str(self.workspace),
                 "--title", "Git task", "--goal", "Finish a synthetic Git task", "--actor", "agent-a")

    def test_ambient_git_overrides_cannot_redirect_the_explicit_workspace(self):
        expected = handoff.snapshot(self.workspace, [])
        with mock.patch.dict(os.environ, {
            "GIT_DIR": str(self.base / "unrelated-git"),
            "GIT_WORK_TREE": str(self.base / "unrelated-worktree"),
            "GIT_INDEX_FILE": str(self.base / "unrelated-index"),
        }):
            self.assertEqual(handoff.snapshot(self.workspace, []), expected)

    def test_recorded_identity_and_manifest_bind_the_repository(self):
        self.initialize()
        snapshot = self.store.load("work")["snapshot"]
        self.assertFalse(snapshot["no_git"])
        self.assertEqual(snapshot["git"]["branch"], "synthetic-main")
        self.assertEqual(snapshot["git"]["head"],
                         subprocess.run(["git", "-C", str(self.workspace), "rev-parse", "HEAD"],
                                        check=True, capture_output=True).stdout.decode().strip())
        self.assertIn("tracked.txt", snapshot["files"])
        self.assertIn(".gitignore", snapshot["files"])
        self.assertNotIn("ignored.txt", snapshot["files"])
        self.cli("check", "--task", "work")

    def test_staged_only_change_trips_the_git_fingerprint_without_worktree_drift(self):
        self.initialize()
        recorded = self.store.load("work")["snapshot"]["fingerprint"]
        (self.workspace / "tracked.txt").write_text("two\n", encoding="utf-8")
        self.git("add", "tracked.txt")
        (self.workspace / "tracked.txt").write_text("one\n", encoding="utf-8")
        result = json.loads(self.cli("check", "--task", "work", code=3))
        self.assertEqual(result["changed_files"], [])
        self.assertFalse(result["git_matches"])
        self.assertNotEqual(result["live_fingerprint"], recorded)

    def test_new_commit_moves_the_git_identity_only(self):
        self.initialize()
        self.git("commit", "-q", "--allow-empty", "-m", "synthetic second commit")
        result = json.loads(self.cli("check", "--task", "work", code=3))
        self.assertEqual(result["changed_files"], [])
        self.assertFalse(result["git_matches"])

    def test_untracked_files_are_drift_while_ignored_changes_are_invisible(self):
        self.initialize()
        (self.workspace / "added.txt").write_text("synthetic\n", encoding="utf-8")
        self.assertEqual(json.loads(self.cli("check", "--task", "work", code=3))["changed_files"],
                         ["added.txt"])
        (self.workspace / "ignored.txt").write_text("changed but still ignored\n", encoding="utf-8")
        self.assertEqual(json.loads(self.cli("check", "--task", "work", code=3))["changed_files"],
                         ["added.txt"])

    def test_repository_subdirectory_cannot_be_registered_as_the_workspace(self):
        nested = self.workspace / "nested"
        nested.mkdir()
        with self.assertRaisesRegex(handoff.HandoffError, "WORKSPACE_NOT_GIT_ROOT"):
            handoff.snapshot(nested, [], no_git=False)

    def test_no_git_task_inside_a_repository_never_claims_git_state(self):
        self.cli("init", "--task", "plain", "--workspace", str(self.workspace),
                 "--title", "Plain task", "--goal", "Finish a synthetic plain task",
                 "--actor", "agent-a", "--no-git", "--scope", "tracked.txt")
        snapshot = self.store.load("plain")["snapshot"]
        self.assertTrue(snapshot["no_git"])
        self.assertIsNone(snapshot["git"])


if __name__ == "__main__":
    unittest.main()
