# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 4.0)

project(holoscan_camera
    VERSION 1.0.0
    DESCRIPTION "Camera capture implementations for Holoscan SDK 5"
    LANGUAGES CXX
)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

if(NOT TARGET holoscan::core OR NOT TARGET holoscan::sensor_io)
    find_package(holoscan 5 REQUIRED COMPONENTS core sensor_io)
endif()

# The standalone package build is an FHS package. holoscan-cli defines
# PKG_holoscan_camera on its configure command line, so this is set before
# GNUInstallDirs and before applications/operators declare install destinations.
if(PKG_holoscan_camera AND (PROJECT_IS_TOP_LEVEL OR HOLOSCAN_CAMERA_BUILD_DEB))
    set(CMAKE_INSTALL_PREFIX "/usr" CACHE PATH
        "Install prefix for the holoscan-camera binary package" FORCE)
    if(NOT CMAKE_LIBRARY_ARCHITECTURE)
        message(FATAL_ERROR
            "holoscan-camera packaging requires a GNU multiarch library architecture")
    endif()
    set(CMAKE_INSTALL_LIBDIR "lib/${CMAKE_LIBRARY_ARCHITECTURE}" CACHE STRING
        "Multiarch library directory for the holoscan-camera binary package" FORCE)
endif()

# ---------------------------------------------------------------------------
# Install layout
# ---------------------------------------------------------------------------
# Set a dedicated component to allow granualar installation even when
# building within an external project such as Holoscan SDK
include(GNUInstallDirs)
set(HOLOSCAN_CAMERA_INSTALL_COMPONENT holoscan-camera)
set(HOLOSCAN_CAMERA_EXAMPLES_INSTALL_COMPONENT holoscan-camera-examples)
option(HOLOSCAN_CAMERA_BUILD_DEB
    "Configure the holoscan-camera Debian package (CPack) even when this module is built nested in another project"
    OFF)
option(BUILD_SHARED_LIBS "Build Holoscan Camera libraries as shared libraries" ON)

# Apache-2.0 section 4 requires every redistribution to carry the license and notice.
# A parent project's GNUInstallDirs DOCDIR names the parent (e.g. share/doc/holoscan);
# keep Camera's files in their own directory so they don't overwrite the parent's.
if(NOT PROJECT_IS_TOP_LEVEL)
    set(CMAKE_INSTALL_DOCDIR "${CMAKE_INSTALL_DATAROOTDIR}/doc/${PROJECT_NAME}")
endif()
install(FILES "${CMAKE_CURRENT_SOURCE_DIR}/LICENSE"
    DESTINATION "${CMAKE_INSTALL_DOCDIR}"
    RENAME LICENSE.txt
    COMPONENT ${HOLOSCAN_CAMERA_INSTALL_COMPONENT})
install(FILES "${CMAKE_CURRENT_SOURCE_DIR}/NOTICE"
    DESTINATION "${CMAKE_INSTALL_DOCDIR}"
    COMPONENT ${HOLOSCAN_CAMERA_INSTALL_COMPONENT})

# ---------------------------------------------------------------------------
# Build options
# ---------------------------------------------------------------------------
# Setting HOLOSCAN_CAMERA_BUILD_ALL=ON toggles every subcomponent on, as a simplified alternative
# to explicitly passing "-DOP_<*>=ON -DAPP_<*>=ON -DPKG_<*>=ON". It is used
# for building and packaging all supported components together in one default,
# common build environment, even if those components may not share a runtime
# environment.
#
# Defaults to OFF to avoid failures in supported but nonstandard environments.
# For instance, if the default build environment expects R39.2 (JetPack 7.2.1)
# headers, then building on an R38.5 host (IGX OS 2.0) with mounted CUDA libraries
# may expose incompatible SIPL or Argus development headers. SIPL and Argus are
# not supported on R38.5 in this release.
option(HOLOSCAN_CAMERA_BUILD_ALL OFF "Build all operators, applications, and packages.")

# Holoscan CLI selects languages with HoloHub flags (`--language`, or
# metadata.json). They are mapped on every configure, so a new CLI selection
# applies to an existing build tree. An explicit -DHOLOSCAN_CAMERA_BUILD_<LANGUAGE>
# takes precedence. Without either, C++ is ON and Python follows HOLOSCAN_BUILD_PYTHON.
set(_camera_default_CPP ON)
set(_camera_default_PYTHON OFF)
if(HOLOSCAN_BUILD_PYTHON)
    set(_camera_default_PYTHON ON)
endif()
foreach(_language IN ITEMS CPP PYTHON)
    if(NOT DEFINED HOLOSCAN_CAMERA_BUILD_${_language})
        if(DEFINED HOLOHUB_BUILD_${_language})
            set(HOLOSCAN_CAMERA_BUILD_${_language} "${HOLOHUB_BUILD_${_language}}")
        else()
            set(HOLOSCAN_CAMERA_BUILD_${_language} "${_camera_default_${_language}}")
        endif()
    endif()
endforeach()

# Determine the NVIDIA Board Support Package (BSP) version to
# guide component compatibility heuristics below
if(NOT DEFINED L4T_MAJ_VER AND DEFINED ENV{L4T_MAJ_VER})
    set(L4T_MAJ_VER "$ENV{L4T_MAJ_VER}")
endif()
if(NOT DEFINED L4T_MAJ_VER AND EXISTS "/etc/nv_tegra_release")
    file(STRINGS "/etc/nv_tegra_release" _l4t_release LIMIT_COUNT 1)
    if(_l4t_release MATCHES "^# R([0-9]+)")
        set(L4T_MAJ_VER "${CMAKE_MATCH_1}")
    endif()
endif()

# Wheels have one payload per architecture, independent of the builder's hardware.
# R39 native backends are isolated at import time; they are never built for x86_64.
if(SKBUILD)
    set(OP_v4l2_capture_op ON CACHE BOOL "Include V4L2 in the wheel" FORCE)
    if(CMAKE_SYSTEM_PROCESSOR MATCHES "^(aarch64|arm64)$")
        if(NOT L4T_MAJ_VER STREQUAL "39")
            message(FATAL_ERROR "ARM64 wheels require R39 headers; build with L4T_VERSION=39.2.1")
        endif()
        set(OP_sipl_capture_op ON CACHE BOOL "Include R39 SIPL in the wheel" FORCE)
        set(OP_argus_capture_op ON CACHE BOOL "Include R39 Argus in the wheel" FORCE)
    else()
        set(OP_sipl_capture_op OFF CACHE BOOL "SIPL native bindings require ARM64" FORCE)
        set(OP_argus_capture_op OFF CACHE BOOL "Argus native bindings require ARM64" FORCE)
    endif()
endif()

# R38 containers do not download SIPL headers. Default SIPL targets off for
# source builds so V4L2 works without them. Package builds choose their own
# operator defaults in pkg/CMakeLists.txt.
# R38 (IGX OS 2.0) SIPL source builds are experimental and not supported in
# this release; SIPL is supported only on Jetson AGX Thor with JetPack 7.2.1
# (R39.2). See README.md#supported-platforms.
if(DEFINED L4T_MAJ_VER AND L4T_MAJ_VER MATCHES "^[0-9]+$" AND L4T_MAJ_VER LESS 39)
    message(STATUS "L4T R${L4T_MAJ_VER}: SIPL source builds require matching headers")
    message(WARNING "Argus capture is not verified on IGX R38; its targets require development headers and link libraries")
    if(NOT DEFINED APP_sipl_capture)
        set(APP_sipl_capture OFF CACHE BOOL "Build SIPL sample with supplied R38 headers")
    endif()
    if(NOT DEFINED APP_sipl_frame_saver)
        set(APP_sipl_frame_saver OFF CACHE BOOL "Build SIPL sample with supplied R38 headers")
    endif()
    if(NOT DEFINED APP_sipl_stereo_monitor)
        set(APP_sipl_stereo_monitor OFF CACHE BOOL "Build SIPL sample with supplied R38 headers")
    endif()
    if(NOT DEFINED APP_sipl_player)
        set(APP_sipl_player OFF CACHE BOOL "Build SIPL sample with supplied R38 headers")
    endif()
    if(NOT PKG_holoscan_camera AND NOT DEFINED OP_sipl_capture_op)
        set(OP_sipl_capture_op OFF CACHE BOOL "Build SIPL operator with supplied R38 headers")
    endif()
endif()

# Keep Argus build coverage on ARM64 CI runners without a Jetson runtime. This controls
# test registration only; HOLOSCAN_CAMERA_BUILD_TESTING still builds the unit-test executable.
option(HOLOSCAN_CAMERA_RUN_ARGUS_TESTS
    "Register Argus tests for execution with a compatible Jetson runtime" ON)

option(HOLOSCAN_CAMERA_RUN_SIPL_TESTS
    "Register SIPL Python tests for execution with a compatible BSP runtime" ON)

# ---------------------------------------------------------------------------
# CMake helpers
# ---------------------------------------------------------------------------
list(PREPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")
include(HoloHubConfigHelpers)

add_library(holoscan_camera INTERFACE)
add_library(holoscan::camera ALIAS holoscan_camera)
set_target_properties(holoscan_camera PROPERTIES EXPORT_NAME camera)
install(TARGETS holoscan_camera
    EXPORT holoscan_camera_targets
    COMPONENT ${HOLOSCAN_CAMERA_INSTALL_COMPONENT})

# ---------------------------------------------------------------------------
# Subprojects
# ---------------------------------------------------------------------------

# Order-dependent: Let subprojects register tests
if(HOLOSCAN_CAMERA_BUILD_TESTING)
    enable_testing()
endif()

# Order-dependent: pkg directory can enable subsequent components needed for a given package
add_subdirectory(pkg)

# Order-dependent: applications can enable their required operators
add_subdirectory(applications)

add_subdirectory(operators)

if(HOLOSCAN_CAMERA_BUILD_PYTHON)
    add_subdirectory(python)
endif()

if(HOLOSCAN_CAMERA_BUILD_TESTING AND PKG_holoscan_camera)
    add_subdirectory(tests)
endif()
