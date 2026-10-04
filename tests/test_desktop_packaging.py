import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import build_desktop as build


class DesktopPackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.root=self.base/"source";self.root.mkdir()
        (self.root/"DESKTOP-CANDIDATE.md").write_text("Synthetic candidate")
        (self.root/"package.json").write_text('{"version":"0.0.0"}')
        self.build=self.base/"build";self.build.mkdir()
        self.host=self.base/"host";self.host.mkdir()
        for name in build.HOST_FILES:
            p=self.host/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b"synthetic public host")
        self.backend=self.base/"backend";self.backend.mkdir()
        (self.backend/"AgentCityBackend.exe").write_bytes(b"synthetic public backend")
        self.allowed=["AgentCityBackend.exe"]
        self.patch=patch.object(build,"ROOT",self.root);self.patch.start();self.addCleanup(self.patch.stop)

    def stage(self):return build.stage_package(self.build,self.base,"a"*40,self.host,self.backend,self.allowed,{})

    def test_old_candidate_private_files_are_preserved_and_never_packaged(self):
        old=self.build/"candidate";old.mkdir()
        (old/"desktop-profile.json").write_text("synthetic private pointer")
        (old/"stale-private-log.txt").write_text("synthetic private log")
        (old/"obsolete.dll").write_bytes(b"synthetic obsolete library")
        before={p.name:p.read_bytes() for p in old.iterdir()}
        first,manifest=self.stage();second,other=self.stage()
        self.assertNotEqual(first,second)
        self.assertEqual({p.name:p.read_bytes() for p in old.iterdir()},before)
        for candidate,m in ((first,manifest),(second,other)):
            self.assertEqual(build.safe_tree(candidate),set(m["allowlist"])|{"build-manifest.json"})
            self.assertFalse(any(p.name in before for p in candidate.rglob("*")))
            self.assertEqual(m["sourceCommit"],"a"*40)
        self.assertFalse(any(p.name.startswith(".staging-") for p in self.build.iterdir()))

    def test_unknown_host_files_are_rejected_without_deleting_them(self):
        extra=self.host/"desktop-profile.json";extra.write_text("synthetic pointer")
        with self.assertRaises(ValueError):self.stage()
        self.assertEqual(extra.read_text(),"synthetic pointer")
        self.assertFalse(any(p.name.startswith("candidate-") for p in self.build.iterdir()))

    def test_unknown_backend_files_are_rejected_not_manifested(self):
        extra=self.backend/"stale-private-log.txt";extra.write_text("synthetic log")
        with self.assertRaises(ValueError):self.stage()
        self.assertTrue(extra.is_file())
        self.assertFalse(any(p.name.startswith("candidate-") for p in self.build.iterdir()))

    def test_missing_output_and_traversal_allowlist_fail_before_publish(self):
        (self.host/"AgentCity.exe").unlink()
        with self.assertRaises(ValueError):self.stage()
        self.assertFalse(any(p.name.startswith("candidate-") for p in self.build.iterdir()))
        self.assertFalse((self.build/"build-manifest.json").exists())

    def test_output_manifest_has_exact_copy_set_and_hashes(self):
        import hashlib
        path,m=self.stage()
        self.assertEqual(len(m["files"]),len(build.HOST_FILES)+2)
        self.assertTrue(all(hashlib.sha256((path/f["path"]).read_bytes()).hexdigest()==f["sha256"] for f in m["files"]))
        self.assertEqual(json.loads((path/"build-manifest.json").read_text())["files"],m["files"])


if __name__=="__main__":unittest.main()
