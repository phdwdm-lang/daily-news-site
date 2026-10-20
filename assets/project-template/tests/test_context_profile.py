"""Portable personalization boundaries; all data is isolated fixture evidence."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import context_profile as context
import daily_site as site
import prepare_audit as prepare
import run_audit as gate
import workflow as flow


class ContextProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        self.private = self.project / ".daily-news"
        self.private.mkdir()
        self.config = context.default_config()
        self.started = datetime.now(timezone.utc) - timedelta(minutes=1)
        self.run = self.project / "data/runs/fixture"
        self.run.mkdir(parents=True)
        self.write(self.run / "run.json", {"schema_version": 2, "id": "fixture", "date": "2026-10-20",
                                           "started_at": self.started.isoformat()})
        self.save_config()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(site.canonical(value))

    def save_config(self):
        self.write(self.private / "config.json", self.config)

    def validate_snapshot(self):
        path = self.run / "context/snapshot.json"
        return gate.context_snapshot(prepare.file_record(path, self.project / "data/runs"),
                                     self.project / "data/runs", self.started, "fixture")[0]

    def candidates(self):
        path = self.project / "host-candidates.json"
        value = [{"type": "interest", "text": "比较AI工具的实际使用体验", "sources": [
            {"kind": "conversation", "reference": "host:permitted-summary-fixture", "read_at": self.started.isoformat(),
             "activity_at": "2026-10-10T10:00:00+08:00"}]}]
        self.write(path, value)
        return path, context.save_candidates(self.project, path)["candidates"][0]["id"]

    def confirm(self, fact_id, *, action="confirm", text=None):
        decision = {"id": fact_id, "action": action}
        if text:
            decision["text"] = text
        path = self.project / "host-decisions.json"
        self.write(path, {"receipt": {"method": "host-interaction", "reference": "fixture:user-selected-this-fact",
                                      "confirmed_at": datetime.now(timezone.utc).isoformat()}, "decisions": [decision]})
        return context.review_candidates(self.project, path)

    def test_candidates_are_stable_and_do_not_become_profile_implicitly(self):
        input_path, fact_id = self.candidates()
        rows = json.loads(input_path.read_text())
        rows[0]["sources"][0]["read_at"] = datetime.now(timezone.utc).isoformat()
        self.write(input_path, rows)
        self.assertEqual(context.save_candidates(self.project, input_path)["candidates"][0]["id"], fact_id)
        self.config["context"]["mode"] = "profile"
        self.save_config()
        context.snapshot(self.project, self.run)
        self.assertEqual(self.validate_snapshot()["facts"], [])
        self.assertFalse((self.private / "profile.json").exists())

    def test_explicit_edit_preserves_id_and_records_receipt_not_read_time(self):
        _, fact_id = self.candidates()
        facts = self.confirm(fact_id, action="edit", text="只关注能复现实操的AI工具")["facts"]
        self.assertEqual(facts[0]["id"], fact_id)
        self.assertEqual(facts[0]["text"], "只关注能复现实操的AI工具")
        self.assertNotEqual(facts[0]["confirmed_at"], facts[0]["sources"][0]["activity_at"])
        candidates = site.load_json(self.private / "context-candidates.json")
        self.assertEqual(candidates["candidates"], [])
        self.assertNotIn("text", candidates["reviews"][0])
        self.config["context"]["mode"] = "profile"
        self.save_config()
        context.snapshot(self.project, self.run)
        self.assertEqual(self.validate_snapshot()["facts"], facts)

    def test_ignore_keeps_no_fact_or_candidate_original(self):
        input_path, fact_id = self.candidates()
        self.assertEqual(self.confirm(fact_id, action="ignore")["facts"], [])
        value = site.load_json(self.private / "context-candidates.json")
        self.assertEqual(value["candidates"], [])
        self.assertNotIn("text", value["reviews"][0])
        self.assertEqual(context.save_candidates(self.project, input_path)["candidates"], [])

    def test_missing_actual_confirmation_and_candidate_profile_are_rejected(self):
        _, fact_id = self.candidates()
        decisions = self.project / "decisions.json"
        self.write(decisions, {"receipt": {"method": "inferred", "reference": "guess", "confirmed_at": context.now()},
                               "decisions": [{"id": fact_id, "action": "confirm"}]})
        with self.assertRaisesRegex(site.ValidationError, "实际用户交互"):
            context.review_candidates(self.project, decisions)
        candidate = site.load_json(self.private / "context-candidates.json")["candidates"][0]
        with self.assertRaisesRegex(site.ValidationError, "candidate"):
            context.validate_profile({"schema_version": 1, "facts": [candidate]})

    def test_selected_json_and_markdown_preserve_types_fields_and_true_activity(self):
        source = self.project / "selected.json"
        task = {"id": "p", "type": "project", "text": "做工具对比", "status": "paused", "next": "用户再确认范围"}
        self.write(source, {"facts": [task]})
        markdown = self.project / "selected.md"
        markdown.write_text("# 兴趣\n\n关注内容制作。\n", encoding="utf-8")
        self.config["context"].update(mode="context", sources=[{"id": "projects", "kind": "local", "path": str(source)},
            {"id": "notes", "kind": "local", "path": str(markdown)}])
        self.save_config()
        context.snapshot(self.project, self.run)
        saved = self.validate_snapshot()
        self.assertEqual([fact["type"] for fact in saved["facts"]], ["project", "document"])
        self.assertEqual(saved["facts"][0]["source_fields"], task)
        self.assertEqual(saved["facts"][0]["status"], "source")
        self.assertNotIn("activity_at", saved["facts"][0]["sources"][0])
        source.write_text("changed after snapshot")
        self.assertEqual(self.validate_snapshot(), saved)  # run keeps its actual read bytes

    def test_unreadable_source_requires_explicit_fallback_and_records_failure(self):
        self.config["context"].update(mode="context", sources=[{"id": "missing", "kind": "local", "path": "missing.md"}])
        self.save_config()
        with self.assertRaisesRegex(site.ValidationError, "不可读"):
            context.snapshot(self.project, self.run)
        self.assertFalse((self.run / "context").exists())
        self.config["context"]["fallback"] = "none"
        self.save_config()
        result = context.snapshot(self.project, self.run)
        self.assertEqual(result["effective_mode"], "none")
        self.assertEqual(self.validate_snapshot()["source_errors"][0]["status"], "unavailable")

    def test_profile_fallback_keeps_only_confirmed_facts_and_records_partial_reads(self):
        _, fact_id = self.candidates()
        confirmed = self.confirm(fact_id)["facts"]
        self.write(self.project / "readable.json", [{"type": "project", "text": "来源中的额外计划"}])
        self.config["context"].update(mode="context", fallback="profile", sources=[
            {"id": "readable", "kind": "local", "path": "readable.json"},
            {"id": "missing", "kind": "local", "path": "missing.md"}])
        self.save_config()
        context.snapshot(self.project, self.run)
        snapshot = self.validate_snapshot()
        self.assertEqual(snapshot["effective_mode"], "profile")
        self.assertEqual(snapshot["facts"], confirmed)
        self.assertEqual(len(snapshot["sources"]), 1)
        self.assertEqual(len(snapshot["source_errors"]), 1)

    def test_selected_empty_json_is_preserved_without_inventing_a_task(self):
        self.write(self.project / "empty.json", [])
        self.config["context"].update(mode="context", sources=[{"id": "empty", "kind": "local", "path": "empty.json"}])
        self.save_config()
        context.snapshot(self.project, self.run)
        snapshot = self.validate_snapshot()
        self.assertEqual(snapshot["facts"], [])
        self.assertEqual(snapshot["source_errors"], [])
        self.assertEqual(snapshot["effective_mode"], "context")

    def test_broken_existing_config_is_not_silently_a_generic_default(self):
        config = self.private / "config.json"
        config.unlink()
        config.symlink_to(self.private / "missing-config.json")
        with self.assertRaises(site.ValidationError):
            context.load_config(self.project)

    def test_candidate_file_cannot_be_selected_to_bypass_confirmation(self):
        self.candidates()
        self.config["context"].update(mode="context", sources=[{"id": "bad", "kind": "local", "path": ".daily-news/context-candidates.json"}])
        self.save_config()
        with self.assertRaisesRegex(site.ValidationError, "未确认候选"):
            context.snapshot(self.project, self.run)

    def test_page_requires_real_host_read_and_selected_identity(self):
        evidence = self.project / "page.json"
        self.write(evidence, {"page_id": "page_fixture", "body": "saved page evidence"})
        self.config["context"].update(mode="context", sources=[{"id": "page", "kind": "page", "path": str(evidence),
            "page_id": "page_fixture", "read_at": (self.started - timedelta(minutes=1)).isoformat()}])
        self.save_config()
        with self.assertRaisesRegex(site.ValidationError, "须由宿主重新读取"):
            context.snapshot(self.project, self.run)
        self.config["context"]["sources"][0]["read_at"] = context.now()
        self.save_config()
        context.snapshot(self.project, self.run)
        self.assertEqual(self.validate_snapshot()["facts"][0]["type"], "document")

    def test_snapshot_refresh_preserves_history_and_tampering_is_rejected(self):
        context.snapshot(self.project, self.run)
        with self.assertRaisesRegex(site.ValidationError, "--refresh"):
            context.snapshot(self.project, self.run)
        context.snapshot(self.project, self.run, refresh=True)
        self.assertEqual(len(list((self.run / "context-history").iterdir())), 1)
        path = self.run / "context/snapshot.json"
        snapshot = site.load_json(path)
        snapshot["facts"] = [{"id": "made-up", "type": "interest", "text": "unconfirmed"}]
        self.write(path, snapshot)
        with self.assertRaisesRegex(site.ValidationError, "未确认候选"):
            self.validate_snapshot()

    def test_new_workflow_none_needs_no_tasks_and_packet_omits_private_facts(self):
        run = Path(flow.init_run(runs_root=self.project / "data/runs", run_id="portable")["run_dir"])
        state = flow.load(run)
        for branch in ("builders", "products"):
            (run / branch).mkdir()
        self.write(run / "builders/raw.json", {"status": "ok", "x": [{"tweets": [{"text": "fixture"}]}]})
        self.write(run / "products/products-manifest.json", {"state": "fetched_all_sources", "sources": []})
        flow.checkpoint(run, state, "inputs", runs_root=self.project / "data/runs")
        self.assertEqual(state["phases"]["inputs"]["evidence"]["context_mode"], "none")
        packet = flow.packet(run, state)
        self.assertNotIn("saved_tasks", packet)
        self.assertIsInstance(packet["personalization"]["facts"], int)
        context.snapshot(self.project, run, refresh=True)
        self.assertEqual(flow.reconcile(run, state), "inputs")

    def test_page_init_returns_recoverable_run_when_host_fetch_is_pending(self):
        self.config["context"].update(mode="context", sources=[{"id": "page", "kind": "page", "path": "pending.json",
            "page_id": "page_fixture", "read_at": self.started.isoformat()}])
        self.save_config()
        result = flow.init_run(runs_root=self.project / "data/runs", run_id="page-pending")
        self.assertEqual(result["personalization"]["status"], "needs-input")
        self.assertTrue((Path(result["run_dir"]) / "workflow.json").is_file())


class ContextAuditTests(unittest.TestCase):
    def setUp(self):
        # Existing fixture includes real gate/media/preview checks in a temp tree.
        from test_run_audit import RunAuditTests
        self.fixture = RunAuditTests(methodName="runTest")
        self.fixture.setUp()
        self.root, self.run = self.fixture.root, self.fixture.run
        self.config = context.default_config()
        self.write(self.root / ".daily-news/config.json", self.config)
        self.write(self.run / "run.json", {"schema_version": 2, "id": "test-run", "date": self.fixture.issue["date"],
                                          "started_at": self.fixture.started})

    def tearDown(self):
        self.fixture.tearDown()

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(site.canonical(value))

    def prepare(self, *, personal=False):
        fixture = self.fixture
        if not personal:
            fixture.issue["product"]["personal"] = []
            fixture.audit["media"]["products"] = []
        fixture.flush()
        context.snapshot(self.root, self.run)
        bindings = {"products": copy.deepcopy(fixture.audit["media"]["products"]),
                    "missing_avatars": copy.deepcopy(fixture.audit["media"]["avatars"]), "personal_bindings": []}
        if personal:
            bindings["personal_bindings"] = [{"url": fixture.issue["product"]["personal"][0]["url"],
                                              "context_ids": ["notes:interest"], "fact_types": ["interest"]}]
        for row in bindings["products"] + bindings["missing_avatars"]:
            for category in ("sources", "candidates"):
                for evidence in row["review"].get(category, []):
                    evidence["evidence_path"] = evidence.pop("evidence")["path"]
        path = self.run / "bindings.json"
        self.write(path, bindings)
        result = prepare.create_audit(issue_path=fixture.issue_file, run_dir=self.run,
            builders_raw=Path(fixture.audit["builders"]["raw"]["path"]), bindings_path=path,
            output=fixture.audit_file, assets_root=fixture.resources, runs_root=fixture.runs)
        self.assertEqual(result["context"]["personal_items"], int(personal))
        return site.load_json(fixture.audit_file)

    def test_none_completes_prepare_candidate_signoff_publish_without_todo(self):
        fixture = self.fixture
        audit = self.prepare()
        self.assertEqual(audit["schema_version"], 2)
        self.assertNotIn("todo", audit)
        candidate = site.publish(fixture.issue, fixture.output, fixture.resources, preview_root=self.run / "v2-previews")
        check = self.run / "v2-ego.json"
        self.write(check, {"tool": "ego-lite", "passed": True, "generation": candidate["release"],
            "reviewed_at": (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat(), "media_checks": []})
        result = prepare.signoff(issue_path=fixture.issue_file, audit_path=fixture.audit_file,
            preview_dir=Path(candidate["preview_path"]), ego_check=check, screenshot=self.run / "screen.png",
            assets_root=fixture.resources, runs_root=fixture.runs)
        self.assertEqual(result["status"], "signed")
        fixture.audit = site.load_json(fixture.audit_file)
        self.assertEqual(fixture.cli()[0], 0)

    def test_typed_context_binding_and_missing_id_are_checked(self):
        source = self.root / "selected.json"
        self.write(source, {"facts": [{"id": "interest", "type": "interest", "text": "内容审核方法"}]})
        self.config["context"].update(mode="context", sources=[{"id": "notes", "kind": "local", "path": str(source)}])
        self.write(self.root / ".daily-news/config.json", self.config)
        audit = self.prepare(personal=True)
        audit["personal_bindings"][0]["context_ids"] = ["candidate-that-was-not-confirmed"]
        self.write(self.fixture.audit_file, audit)
        with self.assertRaisesRegex(site.ValidationError, "未确认"):
            gate.validate_run_audit(self.fixture.issue, self.fixture.audit_file, self.fixture.resources, runs_root=self.fixture.runs)


if __name__ == "__main__":
    unittest.main()
