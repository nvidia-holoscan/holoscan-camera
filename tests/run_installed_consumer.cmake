# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

foreach(required_variable IN ITEMS CAMERA_BINARY_DIR CAMERA_CONSUMER_SOURCE_DIR
        CAMERA_TEST_DIR CAMERA_OPERATORS)
    if(NOT DEFINED ${required_variable} OR "${${required_variable}}" STREQUAL "")
        message(FATAL_ERROR "${required_variable} is required")
    endif()
endforeach()

set(install_prefix "${CAMERA_TEST_DIR}/install")
set(consumer_build "${CAMERA_TEST_DIR}/build")
file(REMOVE_RECURSE "${CAMERA_TEST_DIR}")

foreach(component IN ITEMS holoscan-camera holoscan-camera-cmake)
    execute_process(
        COMMAND "${CMAKE_COMMAND}" --install "${CAMERA_BINARY_DIR}"
            --prefix "${install_prefix}" --component "${component}" --config "${CMAKE_BUILD_TYPE}"
        COMMAND_ERROR_IS_FATAL ANY)
endforeach()

file(GLOB_RECURSE camera_configs
    "${install_prefix}/*/holoscan-cameraConfig.cmake"
    "${install_prefix}/*/holoscan-camera-config.cmake")
list(LENGTH camera_configs camera_config_count)
if(NOT camera_config_count EQUAL 1)
    message(FATAL_ERROR "Expected one installed Camera package config")
endif()
list(GET camera_configs 0 camera_config)
get_filename_component(camera_package_dir "${camera_config}" DIRECTORY)

execute_process(
    COMMAND "${CMAKE_COMMAND}" -S "${CAMERA_CONSUMER_SOURCE_DIR}" -B "${consumer_build}"
        "-DCMAKE_PREFIX_PATH=${install_prefix};${CMAKE_PREFIX_PATH}"
        "-Dholoscan-camera_DIR=${camera_package_dir}"
        "-Dholoscan_DIR=${holoscan_DIR}" "-DCAMERA_OPERATORS=${CAMERA_OPERATORS}"
        "-DCMAKE_BUILD_TYPE=${CMAKE_BUILD_TYPE}"
    COMMAND_ERROR_IS_FATAL ANY)
execute_process(
    COMMAND "${CMAKE_COMMAND}" --build "${consumer_build}" --config "${CMAKE_BUILD_TYPE}"
    COMMAND_ERROR_IS_FATAL ANY)
execute_process(
    COMMAND "${CMAKE_CTEST_COMMAND}" --test-dir "${consumer_build}"
        --build-config "${CMAKE_BUILD_TYPE}" --output-on-failure
    COMMAND_ERROR_IS_FATAL ANY)
