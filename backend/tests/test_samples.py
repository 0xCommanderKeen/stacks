from stacks.samples import epub_bytes


def test_original_fixture_bytes_do_not_depend_on_zip_creation_clock(monkeypatch):
    monkeypatch.setattr("zipfile.time.localtime", lambda *args: (2026, 9, 6, 12, 0, 0, 6, 249, 0))
    before = epub_bytes("Stable duplicate")
    monkeypatch.setattr("zipfile.time.localtime", lambda *args: (2026, 9, 7, 12, 1, 2, 0, 250, 0))
    assert epub_bytes("Stable duplicate") == before
