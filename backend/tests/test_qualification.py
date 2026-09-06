import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from stacks.intake import Intake
from stacks.samples import epub_bytes

spec = importlib.util.spec_from_file_location(
    "qualify_intake", Path(__file__).parents[2] / "scripts" / "qualify_intake.py"
)
qualification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qualification)


def test_disposable_intake_report_preserves_originals_and_counts_duplicates(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    for index in range(6):
        (source / f"private-{index}.epub").write_bytes(epub_bytes(f"Private title {index}"))
    prefixes = tmp_path / "prefixes.json"
    prefixes.write_text('[""]')
    monkeypatch.setattr(qualification, "Intake", lambda library: Intake(library, stable_seconds=0))
    report_path = tmp_path / "report.json"
    qualification.run(
        SimpleNamespace(
            source=source,
            prefixes=prefixes,
            data=tmp_path / "catalog",
            report=report_path,
            revision="fixture",
            max_files=6,
            timeout=30,
        )
    )
    report = json.loads(report_path.read_text())
    assert report["acceptance"]["completed"] == 6
    assert report["repeat"]["duplicates"] == 6
    assert report["no_duplicate_growth"] and report["source_observations_unchanged"]
    assert report["byte_identity_mismatches"] == report["managed_originals"] == 0
    assert report["registered_originals"] == 6
    assert "Private title" not in report_path.read_text()
    assert "private-" not in report_path.read_text()
    with pytest.raises(ValueError, match="nonexistent"):
        qualification.run(
            SimpleNamespace(
                source=source,
                data=tmp_path / "catalog",
                report=report_path,
                max_files=6,
                timeout=30,
            )
        )


def test_qualification_rejects_source_writes_and_excessive_selection(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(ValueError, match="outside the source"):
        qualification.run(
            SimpleNamespace(
                source=source,
                data=source / "catalog",
                report=tmp_path / "report",
                max_files=6,
                timeout=30,
            )
        )
    (source / "one.epub").write_bytes(epub_bytes("One"))
    (source / "two.epub").write_bytes(epub_bytes("Two"))
    with pytest.raises(ValueError, match="file limit"):
        qualification.snapshot(source, [""], 1)
    with pytest.raises(ValueError, match="outside its root"):
        qualification.snapshot(source, [".."], 6)
