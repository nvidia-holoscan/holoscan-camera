# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Split an SDK-generated provider stub into an operator facade without changing its types."""

import argparse
import ast
from pathlib import Path
import re


def select_operator(source, operator):
    tree = ast.parse(source)
    declarations = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            declarations[node.name] = node
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            declarations[node.target.id] = node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    declarations[target.id] = node
    if operator not in declarations:
        raise ValueError(f"SDK stub does not declare {operator}")
    # Retain the selected proxy and all of its local parameter/handle declarations.
    required = set()
    pending = {operator}
    while pending:
        name = pending.pop()
        if name in required:
            continue
        required.add(name)
        node = declarations.get(name)
        if node is not None:
            pending.update(
                child.id for child in ast.walk(node) if isinstance(child, ast.Name)
            )
    lines = source.splitlines(keepends=True)
    replacements = []
    for name, node in declarations.items():
        if name == "__all__":
            replacements.append(
                (node.lineno, node.end_lineno, f"__all__: list[str] = [{operator!r}]\n")
            )
        elif name not in required:
            replacements.append((node.lineno, node.end_lineno, ""))
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            retained = [
                alias
                for alias in node.names
                if (alias.asname or alias.name.split(".")[0]) in required
            ]
            if len(retained) != len(node.names):
                node.names = retained
                replacements.append(
                    (
                        node.lineno,
                        node.end_lineno,
                        ast.unparse(node) + "\n" if retained else "",
                    )
                )
    for start, end, text in sorted(replacements, reverse=True):
        lines[start - 1 : end] = [text]
    return re.sub(r"\n{4,}", "\n\n\n", "".join(lines)).rstrip() + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--operator", required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        select_operator(args.input.read_text(encoding="utf-8"), args.operator),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
