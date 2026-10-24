# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# This file is entered via add_holohub_package(holoscan-camera ...) in
# pkg/CMakeLists.txt, which only fires when PKG_holoscan_camera is ON. A standalone
# build uses HoloHub's Debian packaging helper; a nested build can opt into it
# with HOLOSCAN_CAMERA_BUILD_DEB, otherwise it installs the CMake package
# directly into the SDK module layout without including CPack.
if(PROJECT_IS_TOP_LEVEL OR HOLOSCAN_CAMERA_BUILD_DEB)
    include(holohub_configure_deb)

    holohub_configure_deb(
        NAME        "holoscan-camera"
        DESCRIPTION "${PROJECT_DESCRIPTION}"
        VERSION     "${PROJECT_VERSION}"
        VENDOR      "NVIDIA"
        CONTACT     "jjomier@nvidia.com"
        DEPENDS     "holoscan (>= 5.0.0)"
        COMPONENTS  "${HOLOSCAN_CAMERA_INSTALL_COMPONENT}"
        EXPORT_NAME "holoscan_camera_targets"
    )
else()
    # Nested under a parent project (the Holoscan SDK build): no Debian packaging here. Install
    # the export set beside the other Holoscan module exports and the package config in its own
    # discoverable directory so the parent's install tree exposes find_package(holoscan-camera).
    include(CMakePackageConfigHelpers)
    set(_holoscan_camera_cmake_install_dir "${CMAKE_INSTALL_LIBDIR}/cmake/holoscan-camera")
    set(_holoscan_camera_export_install_dir "${CMAKE_INSTALL_LIBDIR}/cmake/holoscan")
    set(_holoscan_camera_package_dir "${CMAKE_CURRENT_BINARY_DIR}/holoscan-camera-package")
    set(ARG_NAME "holoscan-camera")
    configure_package_config_file("${PROJECT_SOURCE_DIR}/cmake/Config.cmake.in"
        "${_holoscan_camera_package_dir}/holoscan-camera-config.cmake"
        INSTALL_DESTINATION "${_holoscan_camera_cmake_install_dir}"
        NO_SET_AND_CHECK_MACRO)
    write_basic_package_version_file(
        "${_holoscan_camera_package_dir}/holoscan-camera-config-version.cmake"
        VERSION "${PROJECT_VERSION}"
        COMPATIBILITY AnyNewerVersion)
    install(EXPORT holoscan_camera_targets
        FILE holoscan-camera-targets.cmake
        NAMESPACE holoscan::
        DESTINATION "${_holoscan_camera_export_install_dir}"
        COMPONENT ${HOLOSCAN_CAMERA_INSTALL_COMPONENT})
    install(FILES
        "${_holoscan_camera_package_dir}/holoscan-camera-config.cmake"
        "${_holoscan_camera_package_dir}/holoscan-camera-config-version.cmake"
        DESTINATION "${_holoscan_camera_cmake_install_dir}"
        COMPONENT ${HOLOSCAN_CAMERA_INSTALL_COMPONENT})
    unset(ARG_NAME)
    unset(_holoscan_camera_package_dir)
    unset(_holoscan_camera_cmake_install_dir)
    unset(_holoscan_camera_export_install_dir)
endif()
