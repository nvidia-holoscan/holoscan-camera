# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# The CLI enables PKG_holoscan_camera. Configure operator choices before the
# operator subdirectories are entered; their install rules already use the
# holoscan-camera component selected by CPack. Applications are not package
# dependencies.
if(PKG_holoscan_camera)
    set(CAMERA_PACKAGE_OPERATORS v4l2_capture_op)

    # The CLI package command does not accept CMake options, so allow an
    # environment choice to seed an otherwise unset operator cache option.
    foreach(_camera_operator IN ITEMS SIPL ARGUS)
        string(TOLOWER "${_camera_operator}" _camera_operator_lower)
        if(NOT DEFINED OP_${_camera_operator_lower}_capture_op AND
           DEFINED ENV{HOLOSCAN_CAMERA_PACKAGE_${_camera_operator}})
            string(TOUPPER "$ENV{HOLOSCAN_CAMERA_PACKAGE_${_camera_operator}}" _camera_package_choice)
            if(_camera_package_choice STREQUAL "ON" OR _camera_package_choice STREQUAL "OFF")
                set(OP_${_camera_operator_lower}_capture_op "${_camera_package_choice}"
                    CACHE BOOL "Build the ${_camera_operator_lower}_capture_op operator")
            elseif(NOT _camera_package_choice STREQUAL "AUTO")
                message(FATAL_ERROR
                    "HOLOSCAN_CAMERA_PACKAGE_${_camera_operator} must be AUTO, ON, or OFF")
            endif()
        endif()
    endforeach()

    # Defaults apply only to a fresh operator cache. Explicit OP_* values and
    # application dependencies can still select their own operators.
    if(CMAKE_SYSTEM_PROCESSOR MATCHES "^(aarch64|arm64)$")
        # On ARM64, default SIPL on unless OP_sipl_capture_op is explicitly off.
        # The packaged SIPL operator is supported only on Jetson AGX Thor with
        # JetPack 7.2.1; R38 package builds need supplied headers and are
        # experimental.
        if(NOT DEFINED OP_sipl_capture_op OR OP_sipl_capture_op)
            list(APPEND CAMERA_PACKAGE_OPERATORS sipl_capture_op)
        endif()
        # On ARM64, default Argus on for R39 or honor an explicit opt-in.
        if((DEFINED L4T_MAJ_VER AND L4T_MAJ_VER MATCHES "^[0-9]+$" AND L4T_MAJ_VER EQUAL 39) AND
           (NOT DEFINED OP_argus_capture_op OR OP_argus_capture_op))
            list(APPEND CAMERA_PACKAGE_OPERATORS argus_capture_op)
        elseif(OP_argus_capture_op)
            # Explicit opt-in
            list(APPEND CAMERA_PACKAGE_OPERATORS argus_capture_op)
        endif()
    endif()
endif()

add_holohub_package(holoscan-camera OPERATORS "${CAMERA_PACKAGE_OPERATORS}")
