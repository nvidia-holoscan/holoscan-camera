# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

if(HOLOSCAN_CAMERA_BUILD_CPP)
    add_subdirectory(cpp)
endif()
# The Python version, python/sipl_player.py, runs from the source tree with the holoscan_camera
# package. Its tests need the package's test environment, which the top-level
# python/CMakeLists.txt sets up after the applications, so that file adds this python/ directory.
if(HOLOSCAN_CAMERA_BUILD_PYTHON)
    set_property(GLOBAL APPEND PROPERTY HOLOSCAN_CAMERA_PYTHON_TEST_DIRS
        "${CMAKE_CURRENT_SOURCE_DIR}/python")
endif()
