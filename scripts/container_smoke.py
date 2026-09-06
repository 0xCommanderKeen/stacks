"""Verify the shipped image, including a full backup restored into a second container."""

import http.cookiejar
import json
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

from stacks.samples import epub_bytes


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True).strip()


def main():
    image = sys.argv[1]
    name = "stacks-smoke-" + uuid4().hex[:10]
    volume = name + "-restore"
    containers = []
    docker("volume", "create", volume)
    try:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for restoring in (False, True):
                container = name + ("-restored" if restoring else "-initial")
                args = [
                    "run",
                    "-d",
                    "--name",
                    container,
                    "-p",
                    "127.0.0.1::8000",
                    "-e",
                    "STACKS_PASSWORD=container-test-password",
                ]
                if restoring:
                    docker(
                        "run",
                        "--rm",
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
                    (root / "backup.zip").write_bytes(request("/api/backup", b"", "POST").read())
                catalog = json.load(request("/api/catalog"))
                assert catalog["items"][0]["title"] == "Restored from the shipped image"
                asset = catalog["items"][0]["editions"][0]["representations"][0]["assets"][0]
                assert request(f"/api/assets/{asset['id']}/download").read() == publication
                html = request("/").read().decode()
                assert "_app/" in html
                # Index HTML alone isn't enough: verify a built JS resource's content type.
                import re

                script = re.search(r'([./]*_app/immutable/entry/start\.[^"\s]+\.js)', html)
                assert script, html
                assert "javascript" in request("/" + script[1].lstrip("./")).headers["Content-Type"]
                print("Restored image passed." if restoring else "Fresh image passed.")
    finally:
        for container in containers:
            subprocess.run(
                ["docker", "rm", "-f", "-v", container], check=False, capture_output=True
            )
        subprocess.run(["docker", "volume", "rm", volume], check=False, capture_output=True)


if __name__ == "__main__":
    main()
