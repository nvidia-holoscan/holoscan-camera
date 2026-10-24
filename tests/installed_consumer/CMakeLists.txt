# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 4.0)
project(camera_installed_consumer LANGUAGES CXX)

find_package(holoscan-camera CONFIG REQUIRED)
if(NOT TARGET holoscan::camera)
    message(FATAL_ERROR "Installed package did not define holoscan::camera")
endif()
get_target_property(camera_links holoscan::camera INTERFACE_LINK_LIBRARIES)
foreach(camera_operator IN ITEMS v4l2_capture_op sipl_capture_op argus_capture_op)
    if(camera_operator IN_LIST CAMERA_OPERATORS)
        if(NOT TARGET holoscan::${camera_operator}
                OR NOT "holoscan::${camera_operator}" IN_LIST camera_links)
            message(FATAL_ERROR "Enabled operator ${camera_operator} missing from the aggregate")
        endif()
    elseif(TARGET holoscan::${camera_operator}
            OR "holoscan::${camera_operator}" IN_LIST camera_links)
        message(FATAL_ERROR "Disabled operator ${camera_operator} exported or linked")
    endif()
endforeach()

add_executable(camera_installed_consumer main.cpp)
target_compile_features(camera_installed_consumer PRIVATE cxx_std_20)
target_link_libraries(camera_installed_consumer PRIVATE holoscan::camera)
include(CTest)
add_test(NAME camera.installed_consumer.smoke COMMAND camera_installed_consumer)
