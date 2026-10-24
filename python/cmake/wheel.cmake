# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# find_package(holoscan) loads the wheel helper exported by the selected SDK.
if(NOT COMMAND holoscan_add_python_wheel_component)
    if(SKBUILD)
        message(FATAL_ERROR "Camera wheels require an SDK exporting HoloscanPythonWheel.cmake")
    endif()
    return()
endif()
set(_camera_wheel_python_files
    ${_camera_python_files} ${_camera_generated_python_files} operators/__init__.py)
# Python API files follow facade selection, not native target selection: x86_64
# wheels advertise the optional backends too, without their BSP-dependent binaries.
foreach(_backend IN LISTS _camera_operator_facades)
    list(APPEND _camera_wheel_python_files operators/${_backend}_capture_op.py)
    if(HOLOSCAN_BUILD_PYTHON_STUBS)
        list(APPEND _camera_wheel_python_files operators/${_backend}_capture_op.pyi)
        if(NOT _backend STREQUAL "v4l2")
            list(APPEND _camera_wheel_python_files _${_backend}.pyi)
        endif()
    endif()
    if(_backend STREQUAL "sipl")
        list(APPEND _camera_wheel_python_files operators/converters.py)
    endif()
endforeach()
set(_camera_wheel_native_targets)
if(TARGET holoscan::v4l2_capture_op)
    list(APPEND _camera_wheel_native_targets NATIVE_TARGETS v4l2_capture_op)
endif()
if(TARGET holoscan::argus_capture_op)
    if(NOT _camera_wheel_native_targets)
        list(APPEND _camera_wheel_native_targets NATIVE_TARGETS)
    endif()
    list(APPEND _camera_wheel_native_targets argus_capture_op)
    list(APPEND _camera_wheel_python_files schema/argus_frame_metadata.py)
endif()
if(TARGET holoscan::sipl_capture_op)
    if(NOT _camera_wheel_native_targets)
        list(APPEND _camera_wheel_native_targets NATIVE_TARGETS)
    endif()
    list(APPEND _camera_wheel_native_targets sipl_capture_op)
    list(APPEND _camera_wheel_python_files schema/sipl_frame_metadata.py)
endif()
if(HOLOSCAN_BUILD_PYTHON_STUBS)
    list(APPEND _camera_wheel_python_files operators/__init__.pyi _camera.pyi)
    if(TARGET holoscan::argus_capture_op)
        list(APPEND _camera_wheel_python_files schema/argus_frame_metadata.pyi)
    endif()
    if(TARGET holoscan::sipl_capture_op)
        list(APPEND _camera_wheel_python_files schema/sipl_frame_metadata.pyi)
    endif()
endif()
holoscan_add_python_wheel_component(
    MODULE camera
    PACKAGE holoscan_camera
    PYTHON_DIRECTORY "${_camera_package}"
    PYTHON_FILES ${_camera_wheel_python_files}
    EXTENSION_TARGET holoscan_camera_python
    ${_camera_wheel_native_targets}
    LIBRARY_RUNPATH "$ORIGIN/../../holoscan/lib"
    EXTENSION_RUNPATH "$ORIGIN/../holoscan/lib")
if(TARGET holoscan::argus_capture_op)
    holoscan_add_python_wheel_extension(
        MODULE camera TARGET holoscan_camera_argus_python
        RUNPATH "$ORIGIN/../holoscan/lib")
    holoscan_add_python_wheel_extension(
        MODULE camera TARGET "${_argus_metadata_codec}"
        DIRECTORY schema RUNPATH "$ORIGIN/../../holoscan/lib")
endif()
if(TARGET holoscan::sipl_capture_op)
    holoscan_add_python_wheel_extension(
        MODULE camera TARGET holoscan_camera_sipl_python
        RUNPATH "$ORIGIN/../holoscan/lib")
    holoscan_add_python_wheel_extension(
        MODULE camera TARGET "${_sipl_metadata_codec}"
        DIRECTORY schema RUNPATH "$ORIGIN/../../holoscan/lib")
    # The portable ARM64 wheel builder has SIPL headers but no Jetson BSP libraries.
    # Preserve loader dependencies so the installed wheel resolves them from the host BSP.
    set(_camera_sipl_wheel_library
        "holoscan_camera/lib/libsipl_capture_op.so.${PROJECT_VERSION_MAJOR}")
    string(CONFIGURE [=[
        find_program(_camera_patchelf patchelf REQUIRED)
        set(_camera_sipl_library "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/@_camera_sipl_wheel_library@")
        execute_process(COMMAND "${_camera_patchelf}" --print-needed "${_camera_sipl_library}"
            OUTPUT_VARIABLE _camera_needed RESULT_VARIABLE _camera_result)
        if(NOT _camera_result EQUAL 0)
            message(FATAL_ERROR "Could not inspect SIPL wheel dependencies")
        endif()
        string(REPLACE "\n" ";" _camera_needed_list "${_camera_needed}")
        foreach(_camera_dependency IN ITEMS libnvsipl.so libnvsipl_query.so
                libnvscibuf.so libnvscisync.so)
            if(NOT _camera_dependency IN_LIST _camera_needed_list)
                execute_process(COMMAND "${_camera_patchelf}" --add-needed
                    "${_camera_dependency}" "${_camera_sipl_library}"
                    RESULT_VARIABLE _camera_result)
                if(NOT _camera_result EQUAL 0)
                    message(FATAL_ERROR "Could not add ${_camera_dependency} to SIPL wheel")
                endif()
            endif()
        endforeach()
    ]=] _camera_sipl_needed_code @ONLY)
    install(CODE "${_camera_sipl_needed_code}"
        COMPONENT holoscan-wheel-camera EXCLUDE_FROM_ALL)
endif()
