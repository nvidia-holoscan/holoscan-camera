#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Check or update explicitly marked SDK dependency references in Camera docs.

Public source baseline: docs/sdk-baseline.json. Internal development image:
internal/docs/sdk-development.json. Wrapper default: holoscan_camera itself.
The CI commit pin and module version remain independent. No network access.
"""

import argparse
import json
import re
from pathlib import Path

DOCUMENTS = ("README.md", "DEVELOPER.md", "internal/docs/development.md")
START = re.compile(r"^<!-- module-docs:([a-z-]+) -->$")
END = re.compile(r"^<!-- /module-docs:([a-z-]+) -->$")
TAG = re.compile(r"v(\d+)\.(\d+)\.(\d+)(?:-(ea\d+|rc\d+))?(?:\.post\d+)?")


def field(root, path, key):
    data = json.loads((root / path).read_text())
    if set(data) != {key} or not isinstance(data[key], str) or not data[key].strip():
        raise ValueError(f"{path} must contain only nonempty string {key}")
    return data[key]


def render(root, key):
    if key == "sdk-source":
        tag = field(root, "docs/sdk-baseline.json", "sdk_source_tag")
        match = TAG.fullmatch(tag)
        if not match:
            raise ValueError("SDK source tag must be vX.Y.Z[-eaN|-rcN][.postN]")
        label = f"{match[1]}.{match[2]}.{match[3]}"
        if match[4]:
            label += " " + match[4].upper()
        return (
            f"The published SDK {label} source tag (`{tag}`) is one baseline; see the\n"
            f"[SDK {label} release notes](https://github.com/nvidia-holoscan/holoscan-sdk/blob/{tag}/RELEASE_NOTES.md)\n"
            "for release details.\n"
        )
    if key == "sdk-ga-image":
        value = field(root, "docs/ga-container.json", "planned_sdk_image")
        if not re.fullmatch(
            r"nvcr\.io/nvidia/clara-holoscan/holoscan:v[0-9]+\.[0-9]+\.[0-9]+-cuda[0-9]+(?:-[a-z0-9]+)?",
            value,
        ):
            raise ValueError("invalid planned public SDK image reference")
        return f"SDK container image reference:\n`{value}`.\n"
    if key == "sdk-development-image":
        value = field(
            root, "internal/docs/sdk-development.json", "sdk_development_image"
        )
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9./:_@-]*", value):
            raise ValueError("invalid SDK development image reference")
        return f"```bash\nexport HOLOSCAN_CLI_BASE_IMAGE={value}\n./holoscan_camera run-container\n```\n"
    if key == "sdk-default-image":
        matches = re.findall(
            r'^export HOLOSCAN_CLI_BASE_IMAGE="\$\{HOLOSCAN_CLI_BASE_IMAGE:-([^}\n]+)\}"$',
            (root / "holoscan_camera").read_text(),
            re.MULTILINE,
        )
        if len(matches) != 1:
            raise ValueError("expected one literal wrapper SDK image default")
        return f"The wrapper's default remains\n`{matches[0]}`.\n"
    raise ValueError(f"unknown documentation key: {key}")


def rewrite(root, text):
    output = []
    active = None
    for line in text.splitlines(keepends=True):
        begin = START.fullmatch(line.rstrip("\r\n"))
        end = END.fullmatch(line.rstrip("\r\n"))
        if begin:
            if active:
                raise ValueError("nested documentation marker")
            active = begin[1]
            output.extend((line, render(root, active)))
        elif end:
            if active != end[1]:
                raise ValueError("unmatched documentation end marker")
            output.append(line)
            active = None
        elif "module-docs:" in line:
            raise ValueError("malformed documentation marker")
        elif active is None:
            output.append(line)
    if active:
        raise ValueError("unclosed documentation marker")
    return "".join(output)


def synchronize(root, write=False):
    changes = {}
    # Validate every document before writing any, so a malformed later file
    # cannot leave an incomplete version update.
    for name in DOCUMENTS:
        path = root / name
        if not path.exists():
            if name.startswith("internal/"):
                continue  # Public exports intentionally omit internal documents.
            raise ValueError(f"missing required document: {name}")
        original = path.read_text()
        updated = rewrite(root, original)
        if updated != original:
            changes[name] = updated
    if write:
        for name, updated in changes.items():
            (root / name).write_text(updated)
    return list(changes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args()
    try:
        changed = synchronize(Path(__file__).resolve().parents[1], args.write)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    if changed:
        print(
            ("Updated: " if args.write else "Documentation drift: ")
            + ", ".join(changed)
        )
        if args.check:
            print("Run python3 tools/sync_doc_versions.py --write and review the diff.")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
