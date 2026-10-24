#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Use the exact interpreter selected by the Camera CLI, including versioned
# executables that share a directory with an older python3.
set -euo pipefail
exec "${HOLOSCAN_CLI_PYTHON_BIN:-python3}" "$@"
