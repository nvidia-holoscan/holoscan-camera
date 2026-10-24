# SPDX-FileCopyrightText: Copyright (c) 2026 Holoscan Team / NVIDIA. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# The Python sipl_player's tests, which the provider's python/CMakeLists.txt adds with its test
# environment: Python_EXECUTABLE and _camera_python_path.
#
# --validate compiles the player's graphs for placeholder cameras without opening one, and
# tests/test_sipl_player.py runs its tiled graph headless with fake cameras. Both need the SIPL
# Python bindings, CuPy (the player imports the converters), the SDK's Vision and Visualization
# Python packages, and a GPU: the plans bind CUDA-device outputs, and HoloViz renders with
# Vulkan. A cross build does not run target Python, so it skips the tests, as does a package
# check that does not finish.
if(NOT TARGET holoscan::sipl_capture_op)
    return()
endif()
set(_player_packages_missing ON)
if(NOT CMAKE_CROSSCOMPILING)
    execute_process(
        COMMAND "${CMAKE_COMMAND}" -E env "PYTHONPATH=${_camera_python_path}"
            "${Python_EXECUTABLE}" -c "import cupy, holoscan_vision, holoscan_visualization"
        RESULT_VARIABLE _player_packages_missing OUTPUT_QUIET ERROR_QUIET TIMEOUT 10)
endif()
if(_player_packages_missing)
    message(STATUS "Skipping the Python sipl_player tests: CuPy or the SDK's Vision or "
        "Visualization Python package is not importable")
    return()
endif()

function(add_sipl_player_python_validation name expected)
    add_test(NAME python-camera.sipl-player-validate-${name}
        COMMAND "${Python_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/sipl_player.py"
            --validate ${ARGN})
    set_tests_properties(python-camera.sipl-player-validate-${name} PROPERTIES
        ENVIRONMENT "PYTHONPATH=${_camera_python_path}"
        PASS_REGULAR_EXPRESSION "graph validation complete \\(${expected}\\)"
        LABELS "python;sipl;plan;gpu" TIMEOUT 120)
endfunction()
add_sipl_player_python_validation(isp "isp, tiled")
add_sipl_player_python_validation(raw "raw, tiled" --raw)
add_sipl_player_python_validation(headless "isp, tiled, headless" --headless)
add_sipl_player_python_validation(raw_headless "raw, tiled, headless" --raw --headless)
# Each scenario runs in a Python process of its own, of up to two minutes.
add_test(NAME python-camera.sipl-player
    COMMAND "${Python_EXECUTABLE}" -m pytest -q
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_sipl_player.py")
set_tests_properties(python-camera.sipl-player PROPERTIES
    ENVIRONMENT
        "PYTHONPATH=${_camera_python_path};CUPY_CACHE_DIR=${CMAKE_BINARY_DIR}/cupy_cache"
    LABELS "python;sipl;unit;gpu" TIMEOUT 300)
