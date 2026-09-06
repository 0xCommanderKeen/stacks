"""Verify the image, readonly registration, and library backup in a second container."""

import http.cookiejar
import io
import json
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

from PIL import Image
from stacks.samples import epub_bytes

REBUILD_CACHES = """
import json
import sys
from pathlib import Path
from stacks.library import Library
from stacks.thumbnails import rebuild
library = Library(Path("/data/restored"), {"archive": Path(sys.argv[1])})
try:
    # These exact cache names live only in this script's fresh restored fixture.
    paths = list(library.managed.glob("*/cover.jpg"))
    paths += list((library.managed / ".covers").glob("*/thumbnail.jpg"))
    for path in paths:
        path.unlink()
    result = rebuild(library)
    print(json.dumps({"removed": len(paths), **result}))
finally:
    library.close()
"""


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True).strip()


def main():
    image = sys.argv[1]
    if len(sys.argv) > 2 and Path(sys.argv[2]).exists():
        raise ValueError("Report output must be a fresh path")
    name = "stacks-smoke-" + uuid4().hex[:10]
    volume = name + "-restore"
    containers = []
    report = {"image": image, "fresh": False, "restored": False}
    previous_cookie = None
    docker("volume", "create", volume)
    try:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # Linux preserves host bind-mount permissions. This directory contains only
            # synthetic test data and must be traversable by the container's UID 10001.
            root.chmod(0o755)
            originals = root / "originals"
            originals.mkdir(mode=0o755)
            external_bytes = epub_bytes("A registered container book")
            (originals / "registered.epub").write_bytes(external_bytes)
            (originals / "registered.epub").chmod(0o444)
            source_stamp = (originals / "registered.epub").stat().st_mtime_ns
            for restoring in (False, True):
                container = name + ("-restored" if restoring else "-initial")
                args = [
                    "run",
                    "-d",
                    "--name",
                    container,
                    "--cpus",
                    "2",
                    "--memory",
                    "2g",
                    "-p",
                    "127.0.0.1::8000",
                    "-e",
                    "STACKS_PASSWORD=container-test-password",
                ]
                mount = "/sources/reconnected" if restoring else "/sources/archive"
                args.extend(
                    [
                        "-v",
                        f"{originals}:{mount}:ro",
                        "-e",
                        "STACKS_SOURCES=" + json.dumps({"archive": mount}),
                    ]
                )
                if restoring:
                    docker(
                        "run",
                        "--rm",
                        "--cpus",
                        "2",
                        "--memory",
                        "2g",
                        "-v",
                        f"{root}:/restore:ro",
                        "-v",
                        f"{volume}:/data",
                        image,
                        "stacks",
                        "restore",
                        "/restore/backup.zip",
                        "--data-dir",
                        "/data/restored",
                    )
                    cache_result = docker(
                        "run",
                        "--rm",
                        "--cpus",
                        "2",
                        "--memory",
                        "2g",
                        "-v",
                        f"{volume}:/data",
                        "-v",
                        f"{originals}:{mount}:ro",
                        image,
                        "python",
                        "-c",
                        REBUILD_CACHES,
                        mount,
                    )
                    report["cache_rebuild"] = json.loads(cache_result)
                    assert report["cache_rebuild"]["removed"] > 0
                    assert report["cache_rebuild"]["unavailable"] == 0
                    args.extend(["-v", f"{volume}:/data", "-e", "STACKS_DATA_DIR=/data/restored"])
                docker(*args, image)
                containers.append(container)
                address = docker("port", container, "8000/tcp")
                base = "http://" + address
                deadline = time.monotonic() + 45
                while True:
                    try:
                        urllib.request.urlopen(base + "/health/ready", timeout=2)
                        break
                    except (OSError, urllib.error.URLError):
                        if time.monotonic() > deadline:
                            raise RuntimeError(docker("logs", container)) from None
                        time.sleep(0.25)
                opener = urllib.request.build_opener(
                    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
                )

                def request(
                    path, content=None, method=None, headers=None, *, opener=opener, base=base
                ):
                    return opener.open(
                        urllib.request.Request(
                            base + path,
                            data=content,
                            method=method,
                            headers={"X-Stacks-Request": "1", **(headers or {})},
                        ),
                        timeout=30,
                    )

                for cookie in (None, previous_cookie) if restoring else (None,):
                    try:
                        request("/api/catalog", headers={"Cookie": cookie} if cookie else {})
                    except urllib.error.HTTPError as error:
                        assert error.code == 401
                    else:
                        raise AssertionError(
                            "Unauthenticated or old-session catalog access succeeded"
                        )
                request(
                    "/api/login",
                    json.dumps({"password": "container-test-password"}).encode(),
                    headers={"Content-Type": "application/json"},
                )
                if not restoring:
                    publication = epub_bytes()
                    result = json.load(
                        request(
                            "/api/import",
                            publication,
                            headers={
                                "Content-Type": "application/epub+zip",
                                "X-Filename": "sample.epub",
                            },
                        )
                    )
                    book = result["work"]
                    request(
                        f"/api/works/{book['id']}",
                        json.dumps(
                            {
                                "revision": 1,
                                "title": "Restored from the shipped image",
                                "authors": ["Stacks"],
                                "description": "Smoke test",
                            }
                        ).encode(),
                        "PATCH",
                        {"Content-Type": "application/json"},
                    )
                    fixtures = Path(__file__).resolve().parents[1] / "backend/tests/fixtures"
                    for filename in ("compressed.cbr", "tone.mp3", "tone.m4a", "listening.m4b"):
                        content = (fixtures / filename).read_bytes()
                        imported = json.load(
                            request(
                                "/api/import",
                                content,
                                headers={
                                    "Content-Type": "application/octet-stream",
                                    "X-Filename": filename,
                                },
                            )
                        )
                        original = imported["work"]["editions"][0]["representations"][0]["assets"][
                            0
                        ]
                        assert request(f"/api/assets/{original['id']}/download").read() == content
                        if filename == "listening.m4b":
                            audio_rep = imported["work"]["editions"][0]["representations"][0]
                            audio_bytes = content
                            request(
                                f"/api/representations/{audio_rep['id']}/progress",
                                json.dumps(
                                    {
                                        "revision": 0,
                                        "asset_id": original["id"],
                                        "position": 3.25,
                                        "speed": 1.25,
                                        "completed": False,
                                    }
                                ).encode(),
                                "PATCH",
                                {"Content-Type": "application/json"},
                            )
                    registered = json.load(
                        request(
                            "/api/sources/register",
                            json.dumps({"root": "archive", "paths": ["registered.epub"]}).encode(),
                            headers={"Content-Type": "application/json"},
                        )
                    )
                    assert registered["work"]["personal"]["default_shelf"] == "archive"
                    book = json.load(request(f"/api/works/{book['id']}"))
                    book = json.load(
                        request(
                            f"/api/works/{book['id']}/personal",
                            json.dumps(
                                {
                                    "revision": book["revision"],
                                    "notes": "Keep this note",
                                    "rating": 4,
                                    "tags": ["recovery"],
                                }
                            ).encode(),
                            "PATCH",
                            {"Content-Type": "application/json"},
                        )
                    )
                    picture = io.BytesIO()
                    Image.new("RGB", (80, 120), "#344c40").save(picture, "PNG")
                    chosen_bytes = picture.getvalue()
                    book = json.load(
                        request(
                            f"/api/works/{book['id']}/cover?revision={book['revision']}",
                            chosen_bytes,
                            "POST",
                            {"Content-Type": "image/png"},
                        )
                    )
                    collection = json.load(
                        request(
                            "/api/collections",
                            json.dumps({"name": "Recovery shelf"}).encode(),
                            "POST",
                            {"Content-Type": "application/json"},
                        )
                    )
                    request(
                        f"/api/collections/{collection['id']}/entries",
                        json.dumps(
                            {
                                "revision": collection["revision"],
                                "action": "add",
                                "work_id": book["id"],
                            }
                        ).encode(),
                        "POST",
                        {"Content-Type": "application/json"},
                    )
                    previous_cookie = "; ".join(
                        f"{cookie.name}={cookie.value}"
                        for handler in opener.handlers
                        if isinstance(handler, urllib.request.HTTPCookieProcessor)
                        for cookie in handler.cookiejar
                    )
                    assert previous_cookie
                    (root / "backup.zip").write_bytes(request("/api/backup", b"", "POST").read())
                    (root / "backup.zip").chmod(0o644)
                external = json.load(request("/api/catalog?q=registered&scope=archive"))["items"][0]
                original = external["editions"][0]["representations"][0]["assets"][0]
                assert original["root"] == "archive"
                registered_rep = registered["work"]["editions"][0]["representations"][0]
                assert external["id"] == registered["work"]["id"]
                assert external["editions"][0]["representations"][0]["id"] == registered_rep["id"]
                assert original["id"] == registered_rep["assets"][0]["id"]
                assert request(f"/api/assets/{original['id']}/download").read() == external_bytes
                assert (originals / "registered.epub").read_bytes() == external_bytes
                assert (originals / "registered.epub").stat().st_mtime_ns == source_stamp
                catalog = json.load(request("/api/catalog?q=Restored"))
                assert catalog["items"][0]["title"] == "Restored from the shipped image"
                asset = catalog["items"][0]["editions"][0]["representations"][0]["assets"][0]
                assert request(f"/api/assets/{asset['id']}/download").read() == publication
                restored_book = catalog["items"][0]
                assert restored_book["id"] == book["id"]
                expected_rep = book["editions"][0]["representations"][0]
                assert (
                    restored_book["editions"][0]["representations"][0]["id"] == expected_rep["id"]
                )
                assert asset["id"] == expected_rep["assets"][0]["id"]
                assert restored_book["personal"]["notes"] == "Keep this note"
                assert restored_book["personal"]["rating"] == 4
                assert restored_book["personal"]["tags"] == ["recovery"]
                assert restored_book["selected_cover_id"] == book["selected_cover_id"]
                assert request(f"/api/works/{book['id']}/cover/original").read() == chosen_bytes
                assert request(f"/api/works/{book['id']}/cover").read()
                members = json.load(request(f"/api/collections/{collection['id']}/works"))
                assert [entry["work"]["id"] for entry in members["items"]] == [book["id"]]
                playback = json.load(request(f"/api/representations/{audio_rep['id']}/playback"))
                assert playback["progress"]["position"] == 3.25
                assert playback["progress"]["speed"] == 1.25
                assert playback["progress"]["asset_id"] == audio_rep["assets"][0]["id"]
                response = request(
                    f"/api/assets/{audio_rep['assets'][0]['id']}/stream",
                    headers={"Range": "bytes=0-63"},
                )
                assert response.status == 206 and response.read() == audio_bytes[:64]
                report["restored" if restoring else "fresh"] = True
                html = request("/").read().decode()
                assert "_app/" in html
                # Index HTML alone isn't enough: verify a built JS resource's content type.
                import re

                script = re.search(r'([./]*_app/immutable/entry/start\.[^"\s]+\.js)', html)
                assert script, html
                assert "javascript" in request("/" + script[1].lstrip("./")).headers["Content-Type"]
                print("Restored image passed." if restoring else "Fresh image passed.")
        report["verified"] = [
            "managed bytes",
            "read-only relocated external bytes",
            "work/representation/asset IDs",
            "notes/rating/tags",
            "collection membership",
            "chosen cover original and rebuilt thumbnail",
            "audio progress and Range",
            "unauthenticated and pre-backup session denial",
            "built frontend assets",
        ]
        if len(sys.argv) > 2:
            with Path(sys.argv[2]).open("x") as output:
                json.dump(report, output, indent=2)
                output.write("\n")
    finally:
        for container in containers:
            subprocess.run(
                ["docker", "rm", "-f", "-v", container], check=False, capture_output=True
            )
        subprocess.run(["docker", "volume", "rm", volume], check=False, capture_output=True)


if __name__ == "__main__":
    main()
