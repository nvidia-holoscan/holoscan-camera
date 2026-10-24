# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set(camera_operators "")
foreach(camera_operator IN ITEMS v4l2_capture_op sipl_capture_op argus_capture_op)
    if(TARGET holoscan::${camera_operator})
        list(APPEND camera_operators ${camera_operator})
    endif()
endforeach()

add_test(NAME camera.installed_consumer
    COMMAND ${CMAKE_COMMAND}
        "-DCAMERA_BINARY_DIR=${PROJECT_BINARY_DIR}"
        "-DCAMERA_CONSUMER_SOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/installed_consumer"
        "-DCAMERA_TEST_DIR=${CMAKE_CURRENT_BINARY_DIR}/installed-consumer"
        "-DCAMERA_OPERATORS=${camera_operators}"
        "-Dholoscan_DIR=${holoscan_DIR}"
        "-DCMAKE_PREFIX_PATH=${CMAKE_PREFIX_PATH}"
        "-DCMAKE_BUILD_TYPE=$<CONFIG>"
        -P "${CMAKE_CURRENT_SOURCE_DIR}/run_installed_consumer.cmake")
set_tests_properties(camera.installed_consumer PROPERTIES LABELS "package" RUN_SERIAL TRUE)
