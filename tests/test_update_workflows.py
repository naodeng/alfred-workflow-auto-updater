import io
import plistlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import update_workflows as uw


class UpdateWorkflowsTests(unittest.TestCase):
    def test_normalize_repo(self):
        self.assertEqual(uw.normalize_repo("owner/repo"), "owner/repo")
        self.assertEqual(uw.normalize_repo("https://github.com/owner/repo"), "owner/repo")
        self.assertEqual(uw.normalize_repo("git@github.com:owner/repo.git"), "owner/repo")
        self.assertEqual(uw.normalize_repo("https://github.com/owner/repo/"), "owner/repo")
        self.assertIsNone(uw.normalize_repo("https://example.com/x/y"))

    def test_version_compare(self):
        self.assertEqual(uw.parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(uw.parse_version("2025.01-beta"), (2025, 1))
        self.assertFalse(uw.parse_version("alpha"))

        self.assertTrue(uw.is_newer("1.2.3", "1.2.4"))
        self.assertFalse(uw.is_newer("1.2.3", "1.2.3"))
        self.assertFalse(uw.is_newer("1.2", "1.2.0"))
        self.assertTrue(uw.is_newer("1.2.9", "1.10.0"))

    def test_read_workflow_meta_from_webaddress(self):
        with tempfile.TemporaryDirectory() as td:
            wf_dir = Path(td) / "user.workflow.TEST"
            wf_dir.mkdir(parents=True)
            info = wf_dir / "info.plist"
            with info.open("wb") as f:
                plistlib.dump(
                    {
                        "name": "Sample",
                        "version": "1.0.0",
                        "bundleid": "com.demo.sample",
                        "webaddress": "https://github.com/acme/demo-workflow",
                    },
                    f,
                )

            meta = uw.read_workflow_meta(info)
            self.assertIsNotNone(meta)
            self.assertEqual(meta["repo"], "acme/demo-workflow")
            self.assertEqual(meta["name"], "Sample")

    def test_read_workflow_meta_none_when_repo_missing(self):
        with tempfile.TemporaryDirectory() as td:
            wf_dir = Path(td) / "user.workflow.NONE"
            wf_dir.mkdir(parents=True)
            info = wf_dir / "info.plist"
            with info.open("wb") as f:
                plistlib.dump({"name": "NoRepo", "version": "1.0"}, f)

            self.assertIsNone(uw.read_workflow_meta(info))

    def test_find_candidates_limit_and_self_excluded(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            items = [
                ("user.workflow.1", "com.naodeng.alfred.workflow-updater", "https://github.com/a/self"),
                ("user.workflow.2", "com.test.two", "https://github.com/a/two"),
                ("user.workflow.3", "com.test.three", "https://github.com/a/three"),
            ]
            for dirname, bundleid, web in items:
                wf = base / dirname
                wf.mkdir(parents=True)
                with (wf / "info.plist").open("wb") as f:
                    plistlib.dump(
                        {
                            "name": dirname,
                            "version": "1.0.0",
                            "bundleid": bundleid,
                            "webaddress": web,
                        },
                        f,
                    )

            with patch.object(uw, "ALFRED_WORKFLOWS_DIR", base):
                cands = uw.find_candidates(limit=1)
                self.assertEqual(len(cands), 1)
                self.assertEqual(cands[0]["bundleid"], "com.test.two")

    def test_github_latest_release_parsing(self):
        payload = {
            "tag_name": "v2.0.0",
            "html_url": "https://github.com/acme/demo/releases/tag/v2.0.0",
            "assets": [
                {"name": "demo.zip", "browser_download_url": "https://example.com/demo.zip"},
                {
                    "name": "demo.alfredworkflow",
                    "browser_download_url": "https://example.com/demo.alfredworkflow",
                },
            ],
        }

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                import json

                return json.dumps(payload).encode("utf-8")

        with patch("urllib.request.urlopen", return_value=Resp()):
            data = uw.github_latest_release("acme/demo")
            self.assertEqual(data["tag"], "v2.0.0")
            self.assertEqual(data["asset"]["name"], "demo.alfredworkflow")

    def test_enable_auto_invalid_time(self):
        rc = uw.enable_auto(25, 0, quiet=True)
        self.assertEqual(rc, 1)

    def test_enable_auto_success_path(self):
        with patch.object(uw, "write_launch_agent") as w, patch.object(
            uw, "launchctl_bootout"
        ) as bo, patch.object(uw, "launchctl_bootstrap", return_value=True) as bs:
            rc = uw.enable_auto(9, 30, quiet=True)
            self.assertEqual(rc, 0)
            w.assert_called_once_with(9, 30)
            bo.assert_called_once()
            bs.assert_called_once()

    def test_disable_auto_removes_file(self):
        with tempfile.TemporaryDirectory() as td:
            launch_path = Path(td) / "agent.plist"
            launch_path.write_text("x", encoding="utf-8")
            with patch.object(uw, "LAUNCH_AGENT_PATH", launch_path), patch.object(
                uw, "launchctl_bootout"
            ) as bo:
                rc = uw.disable_auto(quiet=True)
                self.assertEqual(rc, 0)
                bo.assert_called_once()
                self.assertFalse(launch_path.exists())

    def test_auto_status_enabled_from_plist(self):
        with tempfile.TemporaryDirectory() as td:
            launch_path = Path(td) / "agent.plist"
            with launch_path.open("wb") as f:
                plistlib.dump({"StartCalendarInterval": {"Hour": 7, "Minute": 15}}, f)
            with patch.object(uw, "LAUNCH_AGENT_PATH", launch_path), patch("sys.stdout", new=io.StringIO()) as out:
                rc = uw.auto_status(quiet=True)
                self.assertEqual(rc, 0)
                self.assertIn("07:15", out.getvalue())

    def test_main_dry_run_message(self):
        fake_args = SimpleNamespace(
            self_test=False,
            enable_auto=False,
            disable_auto=False,
            auto_status=False,
            hour=9,
            minute=0,
            quiet_notify=True,
            dry_run=True,
            max=0,
        )

        with patch.object(uw, "parse_args", return_value=fake_args), patch.object(
            uw, "find_candidates",
            return_value=[{"repo": "a/b", "version": "1.0.0", "bundleid": "b1", "name": "n1"}],
        ), patch.object(
            uw, "github_latest_release",
            return_value={
                "tag": "1.1.0",
                "asset": {"browser_download_url": "https://example.com/x.alfredworkflow"},
                "html_url": "",
            },
        ), patch("sys.stdout", new=io.StringIO()) as out:
            rc = uw.main()
            self.assertEqual(rc, 0)
            self.assertIn("检查完成", out.getvalue())


if __name__ == "__main__":
    unittest.main()
