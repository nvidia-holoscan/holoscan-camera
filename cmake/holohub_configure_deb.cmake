# SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

function(holohub_configure_deb)
  # parse args
  set(options)
  set(requiredArgs NAME DESCRIPTION VERSION VENDOR CONTACT DEPENDS)
  set(oneValueArgs ${requiredArgs} SECTION PRIORITY RECOMMENDS SUGGESTS)
  set(multiValueArgs COMPONENTS EXPORT_NAME)
  cmake_parse_arguments(ARG "${options}" "${oneValueArgs}" "${multiValueArgs}" ${ARGV})

  # validate required args
  foreach(arg ${requiredArgs})
    if(NOT ARG_${arg})
      list(APPEND missingArgs ${arg})
    endif()
  endforeach()
  if(missingArgs)
    message(FATAL_ERROR "Missing required arguments: ${missingArgs}")
  endif()

  if(NOT ARG_SECTION)
   set(ARG_SECTION "devel")
  endif()
  if(NOT ARG_PRIORITY)
    set(ARG_PRIORITY "optional")
  endif()

  # set configurable properties
  set(CPACK_PACKAGE_NAME "${ARG_NAME}")
  set(CPACK_PACKAGE_DESCRIPTION_SUMMARY "${ARG_DESCRIPTION}")
  set(CPACK_PACKAGE_VERSION "${ARG_VERSION}")
  set(CPACK_PACKAGE_VENDOR "${ARG_VENDOR}")
  set(CPACK_PACKAGE_CONTACT "${ARG_CONTACT}")
  set(CPACK_DEBIAN_PACKAGE_DEPENDS "${ARG_DEPENDS}")
  set(CPACK_DEBIAN_PACKAGE_RECOMMENDS "${ARG_RECOMMENDS}")
  set(CPACK_DEBIAN_PACKAGE_SUGGESTS "${ARG_SUGGESTS}")
  set(CPACK_DEBIAN_PACKAGE_SECTION "${ARG_SECTION}")
  set(CPACK_DEBIAN_PACKAGE_PRIORITY "${ARG_PRIORITY}")

  if(ARG_EXPORT_NAME)
    set(config_install_dir "${CMAKE_INSTALL_LIBDIR}/cmake/${ARG_NAME}")
    set(export_install_dir "${CMAKE_INSTALL_LIBDIR}/cmake/holoscan")
    set(export_component ${ARG_NAME}-cmake)
    # Install export files
    install(
      EXPORT ${ARG_EXPORT_NAME}
      DESTINATION ${export_install_dir}
      FILE ${ARG_NAME}-targets.cmake
      NAMESPACE holoscan::
      COMPONENT ${export_component}
    )
    # Generate the config files that include the exports
    include(CMakePackageConfigHelpers)
    configure_package_config_file("${CMAKE_CURRENT_FUNCTION_LIST_DIR}/Config.cmake.in"
      "${CMAKE_CURRENT_BINARY_DIR}/${ARG_NAME}-config.cmake"
      INSTALL_DESTINATION ${config_install_dir}
      NO_SET_AND_CHECK_MACRO
    )
    write_basic_package_version_file(
      "${CMAKE_CURRENT_BINARY_DIR}/${ARG_NAME}-config-version.cmake"
      VERSION "${ARG_VERSION}"
      COMPATIBILITY AnyNewerVersion
    )
    # Install the config files
    install(FILES
      ${CMAKE_CURRENT_BINARY_DIR}/${ARG_NAME}-config.cmake
      ${CMAKE_CURRENT_BINARY_DIR}/${ARG_NAME}-config-version.cmake
      DESTINATION ${config_install_dir}
      COMPONENT ${export_component}
    )
  endif()

  if(ARG_COMPONENTS)
    # only packages installed components, in a single package
    set(CPACK_DEB_COMPONENT_INSTALL 1)
    set(CPACK_ARCHIVE_COMPONENT_INSTALL 1)
    set(CPACK_COMPONENTS_ALL "${ARG_COMPONENTS}")
    if(export_component)
      list(APPEND CPACK_COMPONENTS_ALL "${export_component}")
    endif()
    set(CPACK_COMPONENTS_GROUPING ALL_COMPONENTS_IN_ONE)
  else()
    # package all installed targets
    set(CPACK_DEB_COMPONENT_INSTALL 0)
    set(CPACK_ARCHIVE_COMPONENT_INSTALL 0)
  endif()

  # standard configurations
  if(CMAKE_SYSTEM_PROCESSOR MATCHES "^(x86_64|amd64)$")
    set(package_arch "x86_64")
  elseif(CMAKE_SYSTEM_PROCESSOR MATCHES "^(aarch64|arm64)$")
    set(package_arch "sbsa")
  else()
    message(FATAL_ERROR
      "holoscan-camera packaging supports only x86_64 and SBSA; got ${CMAKE_SYSTEM_PROCESSOR}")
  endif()

  set(CPACK_PACKAGING_INSTALL_PREFIX "/usr")
  set(CPACK_INCLUDE_TOPLEVEL_DIRECTORY OFF)
  set(CPACK_STRIP_FILES TRUE)
  set(CPACK_GENERATOR DEB) # default, can be overridden with cpack -G <generator>
  set(CPACK_DEBIAN_FILE_NAME DEB-DEFAULT)
  # K2 expects the raw archive as <name>-linux-<arch>-<version>.tar.gz.
  set(CPACK_PACKAGE_FILE_NAME
      "${CPACK_PACKAGE_NAME}-linux-${package_arch}-${CPACK_PACKAGE_VERSION}")
  set(CPACK_ARCHIVE_FILE_NAME "${CPACK_PACKAGE_FILE_NAME}")

  # generate package specific CPack configs to allow for multi packages
  set(CPACK_OUTPUT_CONFIG_FILE "${CMAKE_BINARY_DIR}/pkg/CPackConfig-${ARG_NAME}.cmake")
  set(CPACK_SOURCE_OUTPUT_CONFIG_FILE "${CMAKE_BINARY_DIR}/pkg/CPackSourceConfig-${ARG_NAME}.cmake")

  # control scripts
  set(control_scripts "")
  foreach(script IN ITEMS preinst postinst)
    set(script_path "${CMAKE_CURRENT_SOURCE_DIR}/${script}")
    if(EXISTS "${script_path}")
      list(APPEND control_scripts "${script_path}")
    endif()
  endforeach()
  set(CPACK_DEBIAN_PACKAGE_CONTROL_EXTRA ${control_scripts})

  include(CPack)
endfunction()
