from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from herzchen.authoring.snapshots import (
    DurableSnapshotAdapter,
    InvalidSnapshotPath,
    MissingRegisteredFileError,
    SnapshotPathEscape,
    UnregisteredFileError,
    UnsettledWriteError,
    capture_tree,
)
from herzchen.authoring.sessions import AuthoringSessionService, domain_contribution, register_authoring
from herzchen.contracts import AuthenticatedActor, ResourceRef
from herzchen.kernel import Store


class SnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "checkout"
        self.root.mkdir()
        (self.root / "document.txt").write_bytes(b"incomplete\x00draft")
        (self.root / "assets").mkdir()
        (self.root / "assets" / "image.bin").write_bytes(b"\x00\xffexact")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_exact_multi_file_manifest_and_bytes_are_deterministic(self) -> None:
        first = capture_tree(self.root, ["assets/image.bin", "document.txt"])
        second = capture_tree(self.root, ["document.txt", "assets/image.bin"])
        self.assertEqual(first.data, second.data)
        self.assertEqual(first.tree_digest, second.tree_digest)
        self.assertEqual([item.relative_path for item in first.manifest], ["assets/image.bin", "document.txt"])
        self.assertEqual(first.file_bytes("document.txt"), b"incomplete\x00draft")
        self.assertEqual(first.file_bytes("assets/image.bin"), b"\x00\xffexact")

    def test_invalid_paths_missing_and_unregistered_files_are_rejected(self) -> None:
        with self.assertRaises(InvalidSnapshotPath):
            capture_tree(self.root, ["../outside"])
        with self.assertRaises(InvalidSnapshotPath):
            capture_tree(self.root, [str(self.root / "document.txt")])
        with self.assertRaises(MissingRegisteredFileError):
            capture_tree(self.root, ["missing.txt", "document.txt", "assets/image.bin"])
        (self.root / "extra.txt").write_bytes(b"not registered")
        with self.assertRaises(UnregisteredFileError):
            capture_tree(self.root, ["document.txt", "assets/image.bin"])

    def test_symlink_escape_and_unsettled_writer_are_rejected(self) -> None:
        outside = Path(self.tempdir.name) / "outside.txt"
        outside.write_bytes(b"outside")
        (self.root / "escape.txt").symlink_to(outside)
        with self.assertRaises(SnapshotPathEscape):
            capture_tree(self.root, ["document.txt", "assets/image.bin", "escape.txt"])
        (self.root / "escape.txt").unlink()
        with self.assertRaises(UnsettledWriteError):
            capture_tree(self.root, ["document.txt", "assets/image.bin"], settled=False)

    def test_autosave_noop_preserves_raw_draft_and_reads_after_restart(self) -> None:
        db = Path(self.tempdir.name) / "store.sqlite3"
        store = Store.create(db)
        register_authoring(store)
        service = AuthoringSessionService(store)
        opened = service.open(
            ResourceRef("neutral-store", "project", "p-snapshot", "base-1"),
            AuthenticatedActor("auth", "actor", "credential"),
            request_id="open",
            target_kind="project",
            base_revision="base-1",
            initial_content=b"blank",
        )
        adapter = DurableSnapshotAdapter(service)
        saved = adapter.autosave(opened.handle, request_id="save-1", checkout_root=self.root, registered_files=["document.txt", "assets/image.bin"])
        self.assertEqual(saved.status, "saved")
        again = adapter.autosave(opened.handle, request_id="save-2", checkout_root=self.root, registered_files=["document.txt", "assets/image.bin"])
        self.assertEqual(again.status, "no_op")
        ref = saved.session_snapshot.ref
        store.close()
        reopened = Store.open(db, expected_domains=(domain_contribution(),))
        reread = DurableSnapshotAdapter(AuthoringSessionService(reopened)).read(ref)
        self.assertEqual(reread.data, saved.snapshot.data)
        self.assertEqual(reread.file_bytes("document.txt"), b"incomplete\x00draft")
        reopened.close()


if __name__ == "__main__":
    unittest.main()
