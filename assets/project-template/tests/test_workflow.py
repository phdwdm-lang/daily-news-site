import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import daily_site as site
import workflow as flow


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runs = self.root / "data/runs"
        self.run = Path(flow.init_run(runs_root=self.runs, date="2026-10-10", run_id="fixture")["run_dir"])
        self.state = flow.load(self.run)
        self.calls = []
        self.fail_products = False

    def tearDown(self):
        self.tmp.cleanup()

    def runner(self, command, **kwargs):
        branch = "builders" if "builders-source" in command[1] else "products"
        output = Path(command[command.index("--output-dir") + 1])
        self.calls.append(branch)
        value = ({"status": "ok", "x": [{"name": "fixture", "tweets": [{"text": "actual source content"}]}]} if branch == "builders" else
                 {"state": "failed" if self.fail_products else "fetched_all_sources", "sources": []})
        filename = "raw.json" if branch == "builders" else "products-manifest.json"
        (output / filename).write_text(json.dumps(value))
        return subprocess.CompletedProcess(command, int(branch == "products" and self.fail_products), "{}", "")

    def sources_and_todo(self):
        flow.collect(self.run, self.state, runner=self.runner)
        todo = self.run / "todo"
        todo.mkdir()
        (todo / "page.json").write_text(json.dumps({"ref": "visualize:tasks-fixture"}))
        (todo / "source.html").write_text('<script>const tasks=[{"id":"1","status":"done","title":"完整待办"}];</script>')

    def test_modes_and_no_overwrite(self):
        self.assertEqual(self.state["run"]["selection"]["mode"], "as-of")
        with self.assertRaises(site.ValidationError):
            flow.init_run(runs_root=self.runs, date="2026-10-10", run_id="fixture")
        latest = Path(flow.init_run(runs_root=self.runs, run_id="latest")["run_dir"])
        self.assertEqual(flow.load(latest)["run"]["selection"], {"mode": "latest", "date": None})

    def test_successful_resume_does_not_download_or_retimestamp(self):
        flow.collect(self.run, self.state, runner=self.runner)
        previous = json.loads(json.dumps(self.state["branches"]))
        result = flow.collect(self.run, self.state, runner=self.runner)
        self.assertEqual(result["collection"], "reused")
        self.assertCountEqual(self.calls, ["builders", "products"])
        self.assertEqual(self.state["branches"], previous)
        self.assertEqual(len(list((self.run / "attempts").iterdir())), 1)

    def test_failed_branch_only_retries_preserving_attempts(self):
        self.fail_products = True
        flow.collect(self.run, self.state, runner=self.runner)
        old = (self.run / "attempts/0001/products/products-manifest.json").read_bytes()
        builder = self.state["branches"]["builders"].copy()
        self.fail_products = False
        flow.collect(self.run, self.state, runner=self.runner)
        self.assertEqual(self.calls.count("builders"), 1)
        self.assertEqual(self.calls.count("products"), 2)
        self.assertEqual(self.state["branches"]["builders"], builder)
        self.assertEqual((self.run / "attempts/0001/products/products-manifest.json").read_bytes(), old)
        self.assertEqual((self.run / "products").resolve(), self.run / "attempts/0002/products")

    def test_modified_success_is_not_silently_reused(self):
        flow.collect(self.run, self.state, runner=self.runner)
        (self.run / "builders/raw.json").write_text('{"status":"ok","tampered":true}')
        flow.collect(self.run, self.state, runner=self.runner)
        self.assertEqual(self.calls.count("builders"), 2)
        self.assertEqual(self.calls.count("products"), 1)

    def test_new_input_invalidates_all_downstream_and_keeps_history(self):
        self.sources_and_todo()
        flow.checkpoint(self.run, self.state, "inputs", runs_root=self.runs)
        path = self.run / "draft.md"
        path.write_text("完整读取后的工作稿")
        for phase in flow.PHASES[1:]:
            self.state["phases"][phase] = {"status": "complete", "artifacts": [flow.fingerprint(path)]}
        (self.run / "todo/source.html").write_text('const tasks=[{"id":"2"}];')
        self.assertEqual(flow.reconcile(self.run, self.state), "inputs")
        self.assertTrue(all(record["status"] == "stale" for record in self.state["phases"].values()))
        kinds = [json.loads(path.read_text())["kind"] for path in (self.run / "workflow-events").glob("*.json")]
        self.assertEqual(kinds.count("invalidated"), len(flow.PHASES))
        self.assertIn("checkpoint", kinds)

    def test_no_arbitrary_completed_flag_or_skipping_phases(self):
        with self.assertRaises(site.ValidationError):
            flow.checkpoint(self.run, self.state, "review", runs_root=self.runs)
        self.assertEqual(self.state["phases"]["review"]["status"], "failed")
        self.assertIn("前置步骤", flow.load(self.run)["phases"]["review"]["error"])
        with self.assertRaises(site.ValidationError):
            flow.checkpoint(self.run, self.state, "inputs", runs_root=self.runs)

    def test_all_empty_returned_states_are_not_input_success(self):
        self.sources_and_todo()
        (self.run / "builders/raw.json").write_text('{"status":"ok","x":[],"podcasts":[],"blogs":[]}')
        with self.assertRaisesRegex(site.ValidationError, "实际内容为空"):
            flow.checkpoint(self.run, self.state, "inputs", runs_root=self.runs)

    def test_audit_qa_addition_does_not_change_input_checkpoint(self):
        path = self.run / "audit.json"
        path.write_text('{"input":1}')
        original = flow.fingerprint(path, "audit-input")
        path.write_text('{"input":1,"qa":{"passed":true}}')
        self.assertEqual(original, flow.fingerprint(path, "audit-input"))
        path.write_text('{"input":2,"qa":{"passed":true}}')
        self.assertNotEqual(original, flow.fingerprint(path, "audit-input"))

    def test_review_uses_real_gate_and_source_change_is_rejected(self):
        # Reuse the real source/media/browser fixture, never a mock gate.
        from test_run_audit import RunAuditTests
        fixture = RunAuditTests(methodName="runTest")
        fixture.setUp()
        try:
            state = {"run": {"date": fixture.issue["date"], "selection": {"mode": "latest", "date": None}},
                     "branches": {}, "phases": {}, "sequence": 0}
            marker = fixture.run / "marker.txt"
            marker.write_text("verified prerequisite fixture")
            for phase in flow.PHASES[:5]:
                state["phases"][phase] = {"status": "complete", "artifacts": [flow.fingerprint(marker)]}
            flow.checkpoint(fixture.run, state, "review", issue_path=fixture.issue_file,
                            audit_path=fixture.audit_file, assets_root=fixture.resources, runs_root=fixture.runs)
            self.assertEqual(state["phases"]["review"]["status"], "complete")
            fixture.raw["x"][0]["tweets"][0]["text"] = "changed after review"
            Path(fixture.audit["builders"]["raw"]["path"]).write_bytes(site.canonical(fixture.raw))
            with self.assertRaises(site.ValidationError):
                flow.checkpoint(fixture.run, state, "review", issue_path=fixture.issue_file,
                                audit_path=fixture.audit_file, assets_root=fixture.resources, runs_root=fixture.runs)
            self.assertEqual(state["phases"]["review"]["status"], "failed")
        finally:
            fixture.tearDown()

    def test_nonblocking_lock_and_crash_journal_recovery(self):
        with flow.lock(self.run):
            with self.assertRaises(site.ValidationError):
                with flow.lock(self.run):
                    pass
        (self.run / "workflow-events/000002.json").write_text('{"kind":"interrupted"}')
        state = flow.load(self.run)
        self.assertEqual(state["sequence"], 2)
        flow.event(self.run, state, "resumed")
        self.assertTrue((self.run / "workflow-events/000003.json").is_file())

    def test_packet_preserves_all_task_fields_without_raw_duplication(self):
        self.sources_and_todo()
        packet = flow.packet(self.run, self.state)
        self.assertEqual(packet["saved_tasks"][0]["status"], "done")
        self.assertEqual(len(packet["inputs"]), 2)
        self.assertNotIn("x", packet)
        self.assertIn("完整读取", packet["reading_rule"])


if __name__ == "__main__":
    unittest.main()
