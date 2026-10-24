<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Holoscan Camera agent instructions

Paths and commands here and in `.ai-rules/` are relative to the repository root
containing this file, `holoscan_camera`, and `CMakeLists.txt`.

Read [.ai-rules/avoid-generated-search.md](.ai-rules/avoid-generated-search.md)
before searching or selecting repository context: generated build and packaging
output is out of scope unless the task is about it.

Start with [README.md](README.md) for the module overview and
[DEVELOPER.md](DEVELOPER.md) for the layout, the `./holoscan_camera` wrapper
commands, CMake builds without the wrapper, test labels, and packaging.

Before creating a commit, make sure the pre-commit hooks pass. When the git
pre-commit hook is installed (`uvx pre-commit install`), `git commit` runs them
on the staged files; if a hook fails or rewrites files, fix or restage them and
commit again. Without the hook, run `uvx pre-commit run --files <paths>`, or
`uvx pre-commit run --all-files` for a full-tree check.

See [.ai-rules/README.md](.ai-rules/README.md) before changing rule storage or
tool-specific entrypoints.

