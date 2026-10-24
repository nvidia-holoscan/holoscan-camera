# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

get_target_property(_camera_core_type holoscan::core TYPE)
if(_camera_core_type STREQUAL "STATIC_LIBRARY")
    message(FATAL_ERROR "Camera Python bindings require a shared Holoscan Core runtime")
endif()

# nanobind requires FindPython's Python:: targets. Preserve the SDK/CLI's
# Python3_EXECUTABLE selection without performing a second discovery pass.
if(Python3_EXECUTABLE)
    set(Python_EXECUTABLE "${Python3_EXECUTABLE}")
endif()
find_package(Python 3.12 REQUIRED COMPONENTS Interpreter Development.Module Development.SABIModule)

# Prefer CMake package paths (including the SDK's CPM redirect). Query Python only
# as an optional native-build hint; a cross build must not execute target Python.
find_package(nanobind 3.0.1 CONFIG QUIET)
set(_camera_nanobind_hints)
if(NOT nanobind_FOUND AND NOT CMAKE_CROSSCOMPILING)
    execute_process(COMMAND "${Python_EXECUTABLE}" -m nanobind --cmake_dir
        OUTPUT_VARIABLE _camera_nanobind_dir OUTPUT_STRIP_TRAILING_WHITESPACE
        RESULT_VARIABLE _camera_nanobind_result ERROR_QUIET TIMEOUT 10)
    if(_camera_nanobind_result STREQUAL "0" AND _camera_nanobind_dir)
        list(APPEND _camera_nanobind_hints "${_camera_nanobind_dir}")
    endif()
endif()
find_package(nanobind 3.0.1 CONFIG REQUIRED HINTS ${_camera_nanobind_hints})

if(TARGET holoscan_core_python)
    # When the SDK builds Camera as a source subproject (HOLOSCAN_BUILD_CAMERA),
    # reuse its selected nanobind sources and Python build/package paths from
    # the Core Python directory. Installed SDKs do not export the
    # holoscan_core_python target; their Python package is located through
    # holoscan_PYTHON_PACKAGE_DIR, and typing tools are discovered through
    # that installed package.
    get_target_property(_camera_core_python_directory holoscan_core_python SOURCE_DIR)
    get_directory_property(NB_DIR DIRECTORY "${_camera_core_python_directory}" DEFINITION NB_DIR)
    if(NOT DEFINED HOLOSCAN_PYTHON_TOOLS_DIR)
        get_directory_property(HOLOSCAN_PYTHON_TOOLS_DIR
            DIRECTORY "${_camera_core_python_directory}"
            DEFINITION HOLOSCAN_PYTHON_TOOLS_DIR)
    endif()
    if(NOT DEFINED HOLOSCAN_PYTHON_MODULE_ROOT)
        get_directory_property(HOLOSCAN_PYTHON_MODULE_ROOT
            DIRECTORY "${_camera_core_python_directory}"
            DEFINITION HOLOSCAN_PYTHON_MODULE_ROOT)
    endif()
    if(NOT DEFINED HOLOSCAN_PYTHON_INSTALL_DIR)
        get_directory_property(HOLOSCAN_PYTHON_INSTALL_DIR
            DIRECTORY "${_camera_core_python_directory}"
            DEFINITION HOLOSCAN_PYTHON_INSTALL_DIR)
    endif()
endif()

if(NOT DEFINED HOLOSCAN_PYTHON_MODULE_ROOT)
    set(HOLOSCAN_PYTHON_MODULE_ROOT "${PROJECT_BINARY_DIR}/python/lib")
endif()
if(NOT DEFINED HOLOSCAN_PYTHON_INSTALL_DIR)
    set(HOLOSCAN_PYTHON_INSTALL_DIR
        "${CMAKE_INSTALL_LIBDIR}/python${Python_VERSION_MAJOR}.${Python_VERSION_MINOR}/site-packages")
endif()
if(NOT DEFINED HOLOSCAN_BUILD_PYTHON_STUBS)
    if(DEFINED HOLOSCAN_PYTHON_STUBS)
        set(HOLOSCAN_BUILD_PYTHON_STUBS "${HOLOSCAN_PYTHON_STUBS}")
    else()
        set(HOLOSCAN_BUILD_PYTHON_STUBS ON)
    endif()
endif()

set(_camera_package "${HOLOSCAN_PYTHON_MODULE_ROOT}/holoscan_camera")
set(_camera_install "${HOLOSCAN_PYTHON_INSTALL_DIR}/holoscan_camera")

# Plain CMake builds and installs do not run the Python packaging backend.
# Publish the holoscan-camera-cu13 metadata through which Core exposes
# holoscan_camera as holoscan.camera, in the build tree and the install.
holoscan_install_python_module_metadata(
    MODULE camera
    REQUIRES "holoscan-core-cu13==5.0.0")

# Operator selection follows the native targets after application/package dependencies
# have been applied. Enabling Python alone does not enable a capture backend.
set(_camera_operator_imports "")
set(_camera_operator_modules "")
set(_camera_operator_exports "")
set(_camera_operator_bindings)
set(_camera_operator_files)
if(TARGET holoscan::v4l2_capture_op)
    list(APPEND _camera_operator_bindings v4l2)
endif()
if(TARGET holoscan::argus_capture_op)
    list(APPEND _camera_operator_bindings argus)
endif()
if(TARGET holoscan::sipl_capture_op)
    list(APPEND _camera_operator_bindings sipl)
endif()
# Source builds expose selected backends. Wheels advertise every operator facade,
# independently of their architecture-specific native payload; visibility is not capability.
set(_camera_operator_facades ${_camera_operator_bindings})
if(SKBUILD)
    set(_camera_operator_facades v4l2 argus sipl)
endif()
set(_camera_v4l2_name V4l2CaptureOp)
set(_camera_argus_name ArgusCaptureOp)
set(_camera_sipl_name SIPLCaptureOp)
foreach(_backend IN ITEMS v4l2 argus sipl)
    set(_camera_${_backend}_source
        "${CMAKE_CURRENT_SOURCE_DIR}/../operators/${_backend}_capture_op/python")
    if(_backend IN_LIST _camera_operator_facades)
        string(APPEND _camera_operator_imports
            "from .${_backend}_capture_op import ${_camera_${_backend}_name} as ${_camera_${_backend}_name}\n")
        string(APPEND _camera_operator_modules
            "\"${_camera_${_backend}_name}\": \".${_backend}_capture_op\",")
        string(APPEND _camera_operator_exports "\"${_camera_${_backend}_name}\",")
        configure_file("${_camera_${_backend}_source}/${_backend}_capture_op.py"
            "${_camera_package}/operators/${_backend}_capture_op.py" COPYONLY)
        list(APPEND _camera_operator_files "${_camera_package}/operators/${_backend}_capture_op.py")
        install(FILES "${_camera_package}/operators/${_backend}_capture_op.py"
            DESTINATION "${_camera_install}/operators" COMPONENT holoscan-camera-python_libs)
    else()
        # A reconfigured build must not expose a previously enabled operator.
        file(REMOVE "${_camera_package}/operators/${_backend}_capture_op.py"
            "${_camera_package}/operators/${_backend}_capture_op.pyi")
    endif()
endforeach()
configure_file(holoscan_camera/operators/__init__.py.in
    "${_camera_package}/operators/__init__.py" @ONLY)
install(FILES "${_camera_package}/operators/__init__.py"
    DESTINATION "${_camera_install}/operators" COMPONENT holoscan-camera-python_libs)
set(_camera_python_files __init__.py)
if(sipl IN_LIST _camera_operator_facades)
    # SIPL's CuPy operators for its frame formats, kept with the operator, as
    # holoscan_camera.operators.converters. The operators package does not import them: they need
    # CuPy, so a graph imports them on demand.
    configure_file("${_camera_sipl_source}/converters.py"
        "${_camera_package}/operators/converters.py" COPYONLY)
    install(FILES "${_camera_package}/operators/converters.py"
        DESTINATION "${_camera_install}/operators" COMPONENT holoscan-camera-python_libs)
else()
    file(REMOVE "${_camera_package}/operators/converters.py")
endif()
# Configure the schema package for the metadata families enabled in this build. Its directory
# holds only generated files: drop a family's when reconfiguring without it.
set(_camera_schema_imports "")
set(_camera_schema_names)
set(HOLOSCAN_CAMERA_SCHEMA_MODULES "")
if(TARGET holoscan::argus_capture_op)
    string(APPEND _camera_schema_imports
        "from .argus_frame_metadata import ArgusFrameMetadata as ArgusFrameMetadata\n"
        "from .argus_frame_metadata import ArgusTimestampClock as ArgusTimestampClock\n")
    string(APPEND HOLOSCAN_CAMERA_SCHEMA_MODULES
        "\"ArgusFrameMetadata\": \".argus_frame_metadata\", \"ArgusTimestampClock\": \".argus_frame_metadata\",")
    list(APPEND _camera_schema_names ArgusFrameMetadata ArgusTimestampClock)
else()
    file(GLOB _camera_stale_schema "${_camera_package}/schema/*argus_frame_metadata*")
    file(REMOVE ${_camera_stale_schema})
endif()
if(TARGET holoscan::sipl_capture_op)
    string(APPEND _camera_schema_imports
        "from .sipl_frame_metadata import SIPLFrameMetadata as SIPLFrameMetadata\n"
        "from .sipl_frame_metadata import SIPLWbGain as SIPLWbGain\n")
    string(APPEND HOLOSCAN_CAMERA_SCHEMA_MODULES
        "\"SIPLFrameMetadata\": \".sipl_frame_metadata\", \"SIPLWbGain\": \".sipl_frame_metadata\",")
    list(APPEND _camera_schema_names SIPLFrameMetadata SIPLWbGain)
else()
    file(GLOB _camera_stale_schema "${_camera_package}/schema/*sipl_frame_metadata*")
    file(REMOVE ${_camera_stale_schema})
endif()
set(_camera_generated_python_files)
if(_camera_schema_names OR SKBUILD)
    list(JOIN _camera_schema_names "\", \"" _camera_schema_all)
    set(HOLOSCAN_CAMERA_SCHEMA_IMPORTS "${_camera_schema_imports}")
    set(HOLOSCAN_CAMERA_SCHEMA_NAMES "")
    if(_camera_schema_names)
        set(HOLOSCAN_CAMERA_SCHEMA_NAMES "\"${_camera_schema_all}\"")
    endif()
    list(APPEND _camera_generated_python_files schema/__init__.py)
    if(HOLOSCAN_BUILD_PYTHON_STUBS)
        list(APPEND _camera_generated_python_files schema/__init__.pyi)
    endif()
    foreach(_file IN LISTS _camera_generated_python_files)
        if(_file MATCHES "\\.pyi$")
            set(_schema_template holoscan_camera/schema/__init__.pyi.in)
        else()
            set(_schema_template holoscan_camera/schema/__init__.py.in)
        endif()
        configure_file(${_schema_template} "${_camera_package}/${_file}" @ONLY)
        install(FILES "${_camera_package}/${_file}"
            DESTINATION "${_camera_install}/schema" COMPONENT holoscan-camera-python_libs)
    endforeach()
else()
    file(REMOVE_RECURSE "${_camera_package}/schema")
endif()
if(HOLOSCAN_BUILD_PYTHON_STUBS)
    list(APPEND _camera_python_files __init__.pyi py.typed)
    configure_file(holoscan_camera/operators/__init__.pyi.in
        "${_camera_package}/operators/__init__.pyi" @ONLY)
    install(FILES "${_camera_package}/operators/__init__.pyi"
        DESTINATION "${_camera_install}/operators" COMPONENT holoscan-camera-python_libs)
else()
    # Reconfiguring a build without stubs must also remove its old typing markers.
    file(REMOVE "${_camera_package}/__init__.pyi" "${_camera_package}/operators/__init__.pyi"
        "${_camera_package}/operators/v4l2_capture_op.pyi"
        "${_camera_package}/operators/argus_capture_op.pyi"
        "${_camera_package}/operators/sipl_capture_op.pyi"
        "${_camera_package}/schema/__init__.pyi"
        "${_camera_package}/schema/argus_frame_metadata.pyi"
        "${_camera_package}/schema/sipl_frame_metadata.pyi"
        "${_camera_package}/_camera.pyi" "${_camera_package}/py.typed")
endif()
foreach(_file IN LISTS _camera_python_files)
    configure_file("holoscan_camera/${_file}" "${_camera_package}/${_file}" COPYONLY)
    get_filename_component(_directory "${_file}" DIRECTORY)
    install(FILES "${_camera_package}/${_file}"
        DESTINATION "${_camera_install}/${_directory}"
        COMPONENT holoscan-camera-python_libs)
endforeach()

if(HOLOSCAN_BUILD_PYTHON_STUBS AND (_camera_schema_names OR SKBUILD))
    file(APPEND "${_camera_package}/__init__.pyi"
        "\nfrom . import schema as schema\n\n__all__.append(\"schema\")\n")
endif()
if(HOLOSCAN_BUILD_PYTHON_STUBS AND sipl IN_LIST _camera_operator_facades)
    file(APPEND "${_camera_package}/__init__.pyi"
        "\nfrom ._sipl import BayerFormat as BayerFormat\n"
        "from ._sipl import CameraInfo as CameraInfo\n"
        "from ._sipl import PixelFormat as PixelFormat\n"
        "from ._sipl import SIPLCaptureService as SIPLCaptureService\n"
        "\n__all__ += [\"BayerFormat\", \"CameraInfo\", \"PixelFormat\", \"SIPLCaptureService\"]\n")
endif()

nanobind_add_module(holoscan_camera_python NB_STATIC STABLE_ABI _camera.cpp)
target_link_libraries(holoscan_camera_python PRIVATE holoscan::core holoscan::sensor_io)
if(TARGET holoscan::v4l2_capture_op)
    target_link_libraries(holoscan_camera_python PRIVATE holoscan::v4l2_capture_op)
    target_compile_definitions(holoscan_camera_python PRIVATE HOLOSCAN_CAMERA_PYTHON_V4L2)
endif()
file(RELATIVE_PATH _camera_lib_relative "/${_camera_install}" "/${CMAKE_INSTALL_LIBDIR}")
set_target_properties(holoscan_camera_python PROPERTIES
    OUTPUT_NAME _camera
    LIBRARY_OUTPUT_DIRECTORY "${_camera_package}"
    INSTALL_RPATH "\$ORIGIN/${_camera_lib_relative}")
install(TARGETS holoscan_camera_python
    LIBRARY DESTINATION "${_camera_install}" COMPONENT holoscan-camera-python_libs)
# Optional backends have independent ELF dependency closures and registration entrypoints.
foreach(_backend IN ITEMS argus sipl)
    if(TARGET holoscan::${_backend}_capture_op)
        nanobind_add_module(holoscan_camera_${_backend}_python NB_STATIC STABLE_ABI _${_backend}.cpp)
        target_link_libraries(holoscan_camera_${_backend}_python PRIVATE
            holoscan::core holoscan::sensor_io holoscan::${_backend}_capture_op)
        if(_backend STREQUAL "sipl")
            target_link_libraries(holoscan_camera_sipl_python PRIVATE sipl_capture_op_python)
        endif()
        set_target_properties(holoscan_camera_${_backend}_python PROPERTIES
            OUTPUT_NAME _${_backend}
            LIBRARY_OUTPUT_DIRECTORY "${_camera_package}"
            INSTALL_RPATH "\$ORIGIN/${_camera_lib_relative}")
        install(TARGETS holoscan_camera_${_backend}_python
            LIBRARY DESTINATION "${_camera_install}" COMPONENT holoscan-camera-python_libs)
        if(TARGET holoscan-python)
            add_dependencies(holoscan-python holoscan_camera_${_backend}_python)
        endif()
    else()
        file(GLOB _camera_stale_extension "${_camera_package}/_${_backend}.*.so"
            "${_camera_package}/_${_backend}.so")
        file(REMOVE ${_camera_stale_extension})
    endif()
endforeach()
if(HOLOSCAN_BUILD_PYTHON_STUBS AND argus IN_LIST _camera_operator_facades)
    configure_file(holoscan_camera/_argus.pyi "${_camera_package}/_argus.pyi" COPYONLY)
    install(FILES "${_camera_package}/_argus.pyi"
        DESTINATION "${_camera_install}" COMPONENT holoscan-camera-python_libs)
else()
    file(REMOVE "${_camera_package}/_argus.pyi")
endif()
if(HOLOSCAN_BUILD_PYTHON_STUBS AND sipl IN_LIST _camera_operator_facades)
    configure_file(holoscan_camera/_sipl.pyi "${_camera_package}/_sipl.pyi" COPYONLY)
    install(FILES "${_camera_package}/_sipl.pyi"
        DESTINATION "${_camera_install}" COMPONENT holoscan-camera-python_libs)
else()
    file(REMOVE "${_camera_package}/_sipl.pyi")
endif()

# Stage an operator family's generated metadata as holoscan_camera.schema.<module>: the
# SDK-generated dataclass, its stub, and the native conversion adapter. Reusing them keeps the
# Python metadata schema identical to the native metadata port.
function(holoscan_camera_stage_metadata schema_target codec_variable)
    get_target_property(_module ${schema_target} HOLOSCAN_FLATBUFFER_PYTHON_MODULE)
    get_target_property(_stub ${schema_target} HOLOSCAN_FLATBUFFER_PYTHON_STUB)
    get_target_property(_codec ${schema_target} HOLOSCAN_FLATBUFFER_PYTHON_CODEC_TARGET)
    # The SDK always generates schema stubs. Stage only the requested payloads,
    # so disabling typing also removes metadata stubs from the import tree.
    set(_files "${_module}")
    if(HOLOSCAN_BUILD_PYTHON_STUBS)
        list(APPEND _files "${_stub}")
    endif()
    set(_outputs)
    foreach(_file IN LISTS _files)
        get_filename_component(_name "${_file}" NAME)
        set(_output "${_camera_package}/schema/${_name}")
        add_custom_command(OUTPUT "${_output}"
            COMMAND "${CMAKE_COMMAND}" -E copy_if_different "${_file}" "${_output}"
            DEPENDS ${schema_target} "${_file}" VERBATIM)
        list(APPEND _outputs "${_output}")
    endforeach()
    add_custom_target(${schema_target}-python ALL DEPENDS ${_outputs})
    add_dependencies(holoscan_camera_python ${schema_target}-python "${_codec}")
    file(RELATIVE_PATH _lib_relative "/${_camera_install}/schema" "/${CMAKE_INSTALL_LIBDIR}")
    set_target_properties("${_codec}" PROPERTIES
        LIBRARY_OUTPUT_DIRECTORY "${_camera_package}/schema"
        INSTALL_RPATH "\$ORIGIN/${_lib_relative}")
    install(FILES ${_files}
        DESTINATION "${_camera_install}/schema" COMPONENT holoscan-camera-python_libs)
    install(TARGETS "${_codec}"
        LIBRARY DESTINATION "${_camera_install}/schema" COMPONENT holoscan-camera-python_libs)
    set(${codec_variable} "${_codec}" PARENT_SCOPE)
endfunction()
if(TARGET holoscan::argus_capture_op)
    holoscan_camera_stage_metadata(argus_frame_metadata_generated _argus_metadata_codec)
endif()
if(TARGET holoscan::sipl_capture_op)
    holoscan_camera_stage_metadata(sipl_frame_metadata_generated _sipl_metadata_codec)
endif()
if(TARGET holoscan-python)
    add_dependencies(holoscan-python holoscan_camera_python)
endif()

set(_camera_python_paths "${HOLOSCAN_PYTHON_MODULE_ROOT}")
if(holoscan_PYTHON_PACKAGE_DIR)
    # Pass the same Core package to tool discovery, generation, and tests.
    list(APPEND _camera_python_paths "${holoscan_PYTHON_PACKAGE_DIR}")
endif()
list(REMOVE_DUPLICATES _camera_python_paths)
list(JOIN _camera_python_paths ":" _camera_python_path)

if(HOLOSCAN_BUILD_PYTHON_STUBS)
    if(NOT COMMAND holoscan_add_operator_stubs)
        include(HoloscanStubGeneration)
    endif()
    if(NOT COMMAND holoscan_add_operator_stubs)
        message(FATAL_ERROR
            "Camera typing requires the SDK operator-stub tools; see python/README.md")
    endif()
    set(_camera_stub_extensions holoscan_camera_python)
    set(_camera_stub_generator)
    # Wait for source-built Core's Python import prerequisites before
    # generating Camera stubs. The SDK helper collects them through
    # HOLOSCAN_PYTHON_IMPORT_DEPENDENCIES. Installed Core is already built.
    if(TARGET holoscan_core_python)
        # The SDK helper collects Core's initialization/schema prerequisites from
        # its HOLOSCAN_PYTHON_IMPORT_DEPENDENCIES target property.
        list(APPEND _camera_stub_extensions holoscan_core_python)
        # The SDK fetches nanobind through CPM; it need not be installed into Python.
        find_file(_camera_stubgen stubgen.py PATHS "${NB_DIR}/src" "${NB_DIR}"
            NO_DEFAULT_PATH NO_CACHE REQUIRED)
        list(APPEND _camera_stub_generator GENERATOR_SCRIPT "${_camera_stubgen}")
    endif()

    # The extension and operator facades expose different typing surfaces:
    # nanobind describes _camera, while the SDK registry generator describes
    # operator constructors, parameters, and ports exposed through Python proxies.
    holoscan_add_nanobind_stubs(
        TARGET holoscan-camera-python-stubs ALL
        MODULE holoscan_camera._camera
        OUTPUT "${_camera_package}/_camera.pyi"
        EXTENSION_TARGETS ${_camera_stub_extensions}
        PYTHON_EXECUTABLE "${Python_EXECUTABLE}"
        ${_camera_stub_generator}
        PYTHON_PATH ${_camera_python_paths})
    # Keep the public aggregate targets available even for an empty provider.
    add_custom_target(holoscan-camera-operator-stubs ALL)
    add_custom_target(holoscan-camera-check-stubs)
    add_custom_target(holoscan-camera-operator-stub-coverage)
    if(_camera_operator_bindings)
        holoscan_python_tools_directory(_camera_python_tools
            PYTHON_EXECUTABLE "${Python_EXECUTABLE}" PYTHON_PATH ${_camera_python_paths})
        holoscan_add_operator_stubs(
            TARGET holoscan-camera-registry-stubs
            OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/camera_operators.pyi"
            PROVIDER_MODULES holoscan_camera
            REGISTRY_PREFIX "holoscan.camera."
            MODULE_DOC "Camera capture Operators registered by holoscan_camera."
            ${_camera_handle_annotations}
            EXTENSION_TARGETS ${_camera_stub_extensions}
            DEPENDS "${_camera_package}/__init__.py"
                "${_camera_package}/operators/__init__.py"
                ${_camera_operator_files}
            PYTHON_EXECUTABLE "${Python_EXECUTABLE}"
            PYTHON_PATH ${_camera_python_paths})
    endif()
    foreach(_backend IN LISTS _camera_operator_facades)
        if(NOT _backend STREQUAL "v4l2")
            configure_file("${_camera_${_backend}_source}/${_backend}_capture_op.pyi"
                "${_camera_package}/operators/${_backend}_capture_op.pyi" COPYONLY)
            install(FILES "${_camera_package}/operators/${_backend}_capture_op.pyi"
                DESTINATION "${_camera_install}/operators" COMPONENT holoscan-camera-python_libs)
            continue()
        endif()
        # The SDK generator emits one provider-wide stub. Camera exposes separate
        # per-operator modules, so retain each operator and its referenced helper types
        # in the matching .pyi file. This keeps each facade independent of other backends.
        add_custom_command(OUTPUT "${_camera_package}/operators/${_backend}_capture_op.pyi"
            COMMAND "${Python_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/split_operator_stubs.py"
                --input "${CMAKE_CURRENT_BINARY_DIR}/camera_operators.pyi"
                --output "${_camera_package}/operators/${_backend}_capture_op.pyi"
                --operator "${_camera_${_backend}_name}"
            DEPENDS holoscan-camera-registry-stubs
                "${CMAKE_CURRENT_BINARY_DIR}/camera_operators.pyi"
                "${CMAKE_CURRENT_SOURCE_DIR}/split_operator_stubs.py"
            VERBATIM)
        add_custom_target(holoscan-camera-${_backend}-stubs
            DEPENDS "${_camera_package}/operators/${_backend}_capture_op.pyi")
        add_dependencies(holoscan-camera-operator-stubs holoscan-camera-${_backend}-stubs)
        add_custom_target(holoscan-camera-${_backend}-stub-coverage
            COMMAND "${Python_EXECUTABLE}" "${_camera_python_tools}/check_stub_coverage.py"
                --generated "${_camera_package}/operators/${_backend}_capture_op.pyi"
                --committed "${_camera_${_backend}_source}/${_backend}_capture_op.pyi"
                --match-declarations
            DEPENDS "${_camera_python_tools}/check_stub_coverage.py"
                "${_camera_${_backend}_source}/${_backend}_capture_op.pyi"
            VERBATIM)
        add_dependencies(holoscan-camera-${_backend}-stub-coverage holoscan-camera-${_backend}-stubs)
        add_dependencies(holoscan-camera-operator-stub-coverage holoscan-camera-${_backend}-stub-coverage)
        # The stub-coverage target above verifies that the committed stub contains all
        # generated declarations unchanged, including private helper types.
        # This target additionally compares the committed .pyi file in the source tree
        # with the newly generated .pyi file in the build tree, requiring identical contents.
        # Normal builds generate stubs without checking committed copies.
        # CI explicitly builds holoscan-camera-check-stubs to detect differences.
        add_custom_command(TARGET holoscan-camera-check-stubs POST_BUILD
            COMMAND "${CMAKE_COMMAND}" -E compare_files
                "${_camera_${_backend}_source}/${_backend}_capture_op.pyi"
                "${_camera_package}/operators/${_backend}_capture_op.pyi"
            VERBATIM)
        add_dependencies(holoscan-camera-check-stubs holoscan-camera-${_backend}-stub-coverage)
        install(FILES "${_camera_package}/operators/${_backend}_capture_op.pyi"
            DESTINATION "${_camera_install}/operators" COMPONENT holoscan-camera-python_libs)
    endforeach()
    add_custom_target(holoscan-camera-check-r39-stubs)
    foreach(_backend IN ITEMS argus sipl)
        if(NOT TARGET holoscan_camera_${_backend}_python)
            continue()
        endif()
        set(_camera_backend_handle_annotations)
        if(_backend STREQUAL "sipl")
            set(_camera_backend_handle_annotations HANDLE_ANNOTATIONS
                holoscan.camera.SIPLCaptureService=holoscan_camera.SIPLCaptureService)
        endif()
        holoscan_add_operator_stubs(
            TARGET holoscan-camera-${_backend}-registry-stubs
            OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/${_backend}_operators.pyi"
            PROVIDER_MODULES holoscan_camera.operators.${_backend}_capture_op
            REGISTRY_PREFIX "holoscan.camera."
            MODULE_DOC "Camera capture Operators registered by holoscan_camera."
            ${_camera_backend_handle_annotations}
            EXTENSION_TARGETS ${_camera_stub_extensions} holoscan_camera_${_backend}_python
            DEPENDS "${_camera_package}/__init__.py"
                "${_camera_package}/operators/__init__.py"
                "${_camera_package}/schema/__init__.py"
                ${_camera_operator_files}
            PYTHON_EXECUTABLE "${Python_EXECUTABLE}" PYTHON_PATH ${_camera_python_paths})
        add_custom_target(holoscan-camera-check-${_backend}-stubs
            COMMAND "${Python_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/split_operator_stubs.py"
                --input "${CMAKE_CURRENT_BINARY_DIR}/${_backend}_operators.pyi"
                --output "${CMAKE_CURRENT_BINARY_DIR}/${_backend}_checked.pyi"
                --operator "${_camera_${_backend}_name}"
            COMMAND "${Python_EXECUTABLE}" "${_camera_python_tools}/check_stub_coverage.py"
                --generated "${CMAKE_CURRENT_BINARY_DIR}/${_backend}_checked.pyi"
                --committed "${_camera_${_backend}_source}/${_backend}_capture_op.pyi"
                --match-declarations
            COMMAND "${CMAKE_COMMAND}" -E compare_files
                "${CMAKE_CURRENT_BINARY_DIR}/${_backend}_checked.pyi"
                "${_camera_${_backend}_source}/${_backend}_capture_op.pyi"
            VERBATIM)
        add_dependencies(holoscan-camera-check-${_backend}-stubs holoscan-camera-${_backend}-registry-stubs)
        add_dependencies(holoscan-camera-check-r39-stubs holoscan-camera-check-${_backend}-stubs)
    endforeach()
    install(FILES "${_camera_package}/_camera.pyi"
        DESTINATION "${_camera_install}" COMPONENT holoscan-camera-python_libs)
    if(TARGET holoscan-python)
        add_dependencies(holoscan-python
            holoscan-camera-python-stubs holoscan-camera-operator-stubs)
    endif()
endif()

if(HOLOSCAN_CAMERA_BUILD_TESTING)
    set(_camera_v4l2_test_source "${CMAKE_CURRENT_SOURCE_DIR}/tests")
    set(_camera_argus_test_source "${_camera_argus_source}/tests")
    set(_camera_sipl_test_source "${_camera_sipl_source}/tests")
    foreach(_backend IN LISTS _camera_operator_bindings)
        # The C++ graphs that the backends' Python graphs are compared with; SIPL has none.
        if(NOT EXISTS "${_camera_${_backend}_test_source}/${_backend}_plan.cpp")
            continue()
        endif()
        add_executable(${_backend}_python_plan
            "${_camera_${_backend}_test_source}/${_backend}_plan.cpp")
        target_link_libraries(${_backend}_python_plan PRIVATE holoscan::${_backend}_capture_op)
        if(TARGET holoscan-python)
            add_dependencies(holoscan-python ${_backend}_python_plan)
        endif()
    endforeach()
endif()

# Portable tests remain available when an optional runtime is absent.
if(HOLOSCAN_CAMERA_BUILD_TESTING)
    add_test(NAME python-camera.package
        COMMAND "${Python_EXECUTABLE}" -m pytest -q
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_package.py")
    set_tests_properties(python-camera.package PROPERTIES
        ENVIRONMENT "PYTHONPATH=${_camera_python_path};HOLOSCAN_CAMERA_EXPECT_V4L2=$<TARGET_EXISTS:holoscan::v4l2_capture_op>;HOLOSCAN_CAMERA_EXPECT_ARGUS=$<TARGET_EXISTS:holoscan::argus_capture_op>;HOLOSCAN_CAMERA_EXPECT_SIPL=$<TARGET_EXISTS:holoscan::sipl_capture_op>"
        LABELS "python;unit" TIMEOUT 60)
    if(TARGET holoscan::v4l2_capture_op)
        add_test(NAME python-camera.v4l2
            COMMAND "${Python_EXECUTABLE}" -m pytest -q
                "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_v4l2.py"
                "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_v4l2_sample.py")
        set_tests_properties(python-camera.v4l2 PROPERTIES
            ENVIRONMENT
                "PYTHONPATH=${_camera_python_path};HOLOSCAN_CAMERA_PLAN_HELPER=$<TARGET_FILE:v4l2_python_plan>"
            LABELS "python;v4l2;unit" TIMEOUT 60)
    endif()
    if(TARGET holoscan::argus_capture_op AND HOLOSCAN_CAMERA_RUN_ARGUS_TESTS)
        add_test(NAME python-camera.argus
            COMMAND "${Python_EXECUTABLE}" -m pytest -q
                "${_camera_argus_test_source}/test_argus.py")
        set_tests_properties(python-camera.argus PROPERTIES
            ENVIRONMENT
                "PYTHONPATH=${_camera_python_path};HOLOSCAN_CAMERA_PLAN_HELPER=$<TARGET_FILE:argus_python_plan>"
            LABELS "python;argus;unit" TIMEOUT 90)
    endif()
    if(TARGET holoscan::sipl_capture_op AND HOLOSCAN_CAMERA_RUN_SIPL_TESTS)
        # No camera: a SIPLCaptureService initializes NvSIPL only when asked about its cameras.
        add_test(NAME python-camera.sipl
            COMMAND "${Python_EXECUTABLE}" -m pytest -q
                "${_camera_sipl_test_source}/test_sipl.py")
        set_tests_properties(python-camera.sipl PROPERTIES
            ENVIRONMENT "PYTHONPATH=${_camera_python_path}"
            LABELS "python;sipl;unit" TIMEOUT 120)
        # The converters' CUDA kernels on synthetic frames need a GPU, not a camera, and CuPy,
        # which the provider itself does not. Like the nanobind lookup, a cross build does not
        # run target Python: it skips the test, as does a check that does not finish.
        set(_camera_cupy_missing ON)
        if(NOT CMAKE_CROSSCOMPILING)
            execute_process(COMMAND "${Python_EXECUTABLE}" -c "import cupy"
                RESULT_VARIABLE _camera_cupy_missing OUTPUT_QUIET ERROR_QUIET TIMEOUT 10)
        endif()
        if(_camera_cupy_missing)
            message(STATUS "Skipping python-camera.sipl-converters: CuPy is not importable")
        else()
            add_test(NAME python-camera.sipl-converters
                COMMAND "${Python_EXECUTABLE}" -m pytest -q
                    "${_camera_sipl_test_source}/test_sipl_converters.py")
            set_tests_properties(python-camera.sipl-converters PROPERTIES
                ENVIRONMENT
                    "PYTHONPATH=${_camera_python_path};CUPY_CACHE_DIR=${CMAKE_BINARY_DIR}/cupy_cache"
                LABELS "python;sipl;unit;gpu" TIMEOUT 180)
        endif()
    endif()
    # Python applications keep their tests with them: an application lists its directory in
    # HOLOSCAN_CAMERA_PYTHON_TEST_DIRS, and that directory's CMakeLists.txt registers the tests
    # with this test environment (Python_EXECUTABLE, _camera_python_path). The applications are
    # configured before this directory, so it adds theirs.
    get_property(_camera_test_dirs GLOBAL PROPERTY HOLOSCAN_CAMERA_PYTHON_TEST_DIRS)
    foreach(_camera_test_dir IN LISTS _camera_test_dirs)
        file(RELATIVE_PATH _camera_test_binary_dir "${PROJECT_SOURCE_DIR}" "${_camera_test_dir}")
        add_subdirectory("${_camera_test_dir}" "${PROJECT_BINARY_DIR}/${_camera_test_binary_dir}")
    endforeach()
    if(HOLOSCAN_BUILD_PYTHON_STUBS)
        add_test(NAME python-camera.stub-surface
            COMMAND "${Python_EXECUTABLE}" -m pytest -q
                "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_stubs.py")
        # The allowlist covers nanobind artifacts that stubtest cannot model (see the file).
        add_test(NAME python-camera.stubtest
            COMMAND "${Python_EXECUTABLE}" -m mypy.stubtest holoscan_camera._camera
                --allowlist "${CMAKE_CURRENT_SOURCE_DIR}/stubtest_allowlist.txt"
                --ignore-unused-allowlist)
        set_tests_properties(python-camera.stub-surface python-camera.stubtest PROPERTIES
            ENVIRONMENT "PYTHONPATH=${_camera_python_path}"
            LABELS "python;typing" TIMEOUT 120)
        set(_camera_runtime_typing_backends)
        foreach(_backend IN LISTS _camera_operator_bindings)
            if(_backend STREQUAL "v4l2")
                add_test(NAME python-camera.v4l2-stub-drift
                    COMMAND "${CMAKE_COMMAND}" -E compare_files
                        "${_camera_v4l2_source}/v4l2_capture_op.pyi"
                        "${_camera_package}/operators/v4l2_capture_op.pyi")
                set_tests_properties(python-camera.v4l2-stub-drift PROPERTIES
                    LABELS "python;v4l2;typing")
            else()
                string(TOUPPER "${_backend}" _camera_backend_upper)
                if(NOT HOLOSCAN_CAMERA_RUN_${_camera_backend_upper}_TESTS)
                    continue()
                endif()
                # Compare against freshly generated registry declarations, not the
                # committed stub staged for header-only builds. Serialize the build
                # invocation with other CTest work in this build directory.
                add_test(NAME python-camera.${_backend}-stub-drift
                    COMMAND "${CMAKE_COMMAND}" --build "${CMAKE_BINARY_DIR}"
                        --target holoscan-camera-check-${_backend}-stubs)
                set_tests_properties(python-camera.${_backend}-stub-drift PROPERTIES
                    RUN_SERIAL TRUE ENVIRONMENT "PYTHONPATH=${_camera_python_path}"
                    LABELS "python;${_backend};typing" TIMEOUT 180)
                add_test(NAME python-camera.${_backend}-stubtest
                    COMMAND "${Python_EXECUTABLE}" -m mypy.stubtest holoscan_camera._${_backend}
                        --allowlist "${CMAKE_CURRENT_SOURCE_DIR}/stubtest_allowlist.txt"
                        --ignore-unused-allowlist)
                set_tests_properties(python-camera.${_backend}-stubtest PROPERTIES
                    ENVIRONMENT "PYTHONPATH=${_camera_python_path}"
                    LABELS "python;${_backend};typing" TIMEOUT 120)
            endif()
            list(APPEND _camera_runtime_typing_backends "${_backend}")
        endforeach()
        # A build may contain both backends while only SIPL is runnable (for example,
        # Thor). Enable surface checks per backend rather than using a global R39 flag.
        list(JOIN _camera_runtime_typing_backends "," _camera_runtime_typing_backends)
        set_tests_properties(python-camera.stub-surface PROPERTIES
            ENVIRONMENT
                "PYTHONPATH=${_camera_python_path};HOLOSCAN_CAMERA_TEST_BACKENDS=${_camera_runtime_typing_backends}")
        find_program(HOLOSCAN_CAMERA_PYRIGHT_EXECUTABLE pyright REQUIRED)
        holoscan_python_tools_directory(_camera_python_tools
            PYTHON_EXECUTABLE "${Python_EXECUTABLE}" PYTHON_PATH ${_camera_python_paths})
        add_test(NAME python-camera.type-completeness
            COMMAND "${Python_EXECUTABLE}" "${_camera_python_tools}/check_type_completeness.py"
                holoscan_camera --minimum 100 --pyright "${HOLOSCAN_CAMERA_PYRIGHT_EXECUTABLE}")
        set(_camera_typing_tests python-camera.type-completeness)
        if(_camera_operator_bindings)
            add_test(NAME python-camera.typing
                COMMAND "${Python_EXECUTABLE}" -m pytest -q
                    "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_typing.py")
            list(APPEND _camera_typing_tests python-camera.typing)
        endif()
        set_tests_properties(${_camera_typing_tests} PROPERTIES
            ENVIRONMENT
                "PYTHONPATH=${_camera_python_path};HOLOSCAN_CAMERA_PYRIGHT=${HOLOSCAN_CAMERA_PYRIGHT_EXECUTABLE}"
            LABELS "python;typing" TIMEOUT 180)
    endif()
endif()

include("${CMAKE_CURRENT_LIST_DIR}/cmake/wheel.cmake")
