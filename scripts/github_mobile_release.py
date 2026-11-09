#!/usr/bin/env python3
"""Create a new Android prerelease without replacing any existing tag/asset."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

from mobile_release import CHECKSUMS, MANIFEST, REPOSITORY, validate_identity, verify_release


class GitHub:
    def __init__(self, token):
        if not token:
            raise ValueError("GITHUB_TOKEN is required")
        self.token = token

    def request(self, method, path, payload=None, content=None, filename=None):
        if filename is None:
            url = "https://api.github.com/repos/" + REPOSITORY + path
            data = json.dumps(payload).encode() if payload is not None else None
            content_type = "application/json"
        else:
            url = "https://uploads.github.com/repos/" + REPOSITORY + path
            url += "?" + urllib.parse.urlencode({"name": filename})
            data = content
            content_type = "application/octet-stream"
        request = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": "Bearer " + self.token,
            "Accept": "application/vnd.github+json",
            "Content-Type": content_type,
            "X-GitHub-Api-Version": "2022-11-28",
        })
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if method == "GET" and error.code == 404:
                return None
            # Never retry write requests: an ambiguous upload must not replace assets.
            raise RuntimeError(f"GitHub {method} {path} failed ({error.code})") from error


def require_unused(api, tag):
    encoded = urllib.parse.quote(tag, safe="")
    if api.request("GET", "/git/ref/tags/" + encoded) is not None:
        raise ValueError(f"Tag already exists: {tag}; choose a new release_tag")
    if api.request("GET", "/releases/tags/" + encoded) is not None:
        raise ValueError(f"Release already exists: {tag}; choose a new release_tag")


def publish(api, directory, tag, source_commit, request_id="", workflow_run_id=None):
    manifest = verify_release(directory, tag, source_commit, request_id, workflow_run_id)
    require_unused(api, tag)
    # Creating the ref atomically also closes the preflight/build race. A 422 is
    # an error, never permission to force-update someone else's ref.
    api.request("POST", "/git/refs", payload={"ref": "refs/tags/" + tag, "sha": source_commit})
    release = api.request("POST", "/releases", payload={
        "tag_name": tag, "target_commitish": source_commit,
        "name": "Android libmpv " + tag, "draft": True, "prerelease": True,
        "generate_release_notes": False,
        "body": (f"Default flavor, four Android ABIs.\n\nSource: `{source_commit}`.\n"
                 "Checksums and source identity are in the attached manifest.\n"
                 "All packaged 64-bit ELF libraries passed 16 KiB load-segment checks. "
                 "Device playback and final APK/AAB alignment still require application validation.\n"
                 f"\nRequest: `{request_id or 'manual'}`.\n"),
    })
    release_id = release["id"]
    expected = {record["name"]: record for record in manifest["assets"]}
    for name in [*expected, MANIFEST, CHECKSUMS]:
        data = (directory / name).read_bytes()
        asset = api.request("POST", f"/releases/{release_id}/assets", content=data, filename=name)
        if asset.get("name") != name or asset.get("size") != len(data) or asset.get("state") != "uploaded":
            raise ValueError(f"Upload did not complete for {name}; preserve the draft for inspection")
        if asset.get("digest") not in (None, "sha256:" + hashlib.sha256(data).hexdigest()):
            raise ValueError(f"Server upload checksum mismatch: {name}")
    uploaded = api.request("GET", f"/releases/{release_id}/assets")
    if {asset["name"] for asset in uploaded} != set(expected) | {MANIFEST, CHECKSUMS} or len(uploaded) != 6:
        raise ValueError("Uploaded asset set differs; draft has not been published")
    result = api.request("PATCH", f"/releases/{release_id}", payload={"draft": False, "prerelease": True})
    if result.get("draft") is not False or result.get("prerelease") is not True:
        raise ValueError("GitHub did not confirm the prerelease state")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["preflight", "publish"])
    parser.add_argument("--tag", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--request-id", default="")
    parser.add_argument("--workflow-run-id", type=int, default=os.environ.get("GITHUB_RUN_ID"))
    parser.add_argument("--directory", type=Path, default=Path("release"))
    args = parser.parse_args()
    validate_identity(args.tag, args.source_commit, args.request_id, args.workflow_run_id)
    if os.environ.get("GITHUB_REPOSITORY") != REPOSITORY:
        raise ValueError("This publisher only operates in " + REPOSITORY)
    api = GitHub(os.environ.get("GITHUB_TOKEN"))
    if args.command == "preflight":
        require_unused(api, args.tag)
        print("Release/tag are available")
    else:
        if args.workflow_run_id is None:
            raise ValueError("Publishing requires the actual GitHub workflow_run_id")
        result = publish(api, args.directory, args.tag, args.source_commit, args.request_id, args.workflow_run_id)
        print("Published prerelease: " + result["html_url"])
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as stream:
                stream.write(f"Published Android prerelease `{args.tag}` from `{args.source_commit}`.\n\n")
                stream.write(result["html_url"] + "\n")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, RuntimeError) as error:
        raise SystemExit(str(error)) from error
