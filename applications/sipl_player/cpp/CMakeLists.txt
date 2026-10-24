# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# HolovizOp and BayerDemosaicOp come from the SDK's visualization and vision components.
if(NOT TARGET holoscan::visualization::op_holoviz OR NOT TARGET holoscan::vision)
    find_package(holoscan 5 REQUIRED COMPONENTS vision visualization)
endif()

# The --raw path's RAW10 unpack kernel. Default to every major GPU architecture, so building needs
# no GPU (sm_80 code also runs on Jetson Orin's sm_87).
if(NOT DEFINED CMAKE_CUDA_ARCHITECTURES AND NOT DEFINED ENV{CUDAARCHS})
    set(CMAKE_CUDA_ARCHITECTURES all-major)
endif()
enable_language(CUDA)
find_package(CUDAToolkit REQUIRED COMPONENTS cudart)

add_executable(sipl_player sipl_player.cpp raw10_unpack.cu)

target_compile_features(sipl_player PRIVATE cxx_std_20)

# One CUDA runtime in the process: SIPLCaptureOp uses the shared one.
set_target_properties(sipl_player PROPERTIES CUDA_RUNTIME_LIBRARY Shared)

target_link_libraries(sipl_player PRIVATE
    holoscan::sipl_capture_op
    holoscan::core
    holoscan::vision
    holoscan::visualization::op_holoviz
    CUDA::cudart)

target_link_options(sipl_player PRIVATE "LINKER:--allow-shlib-undefined")

include(GNUInstallDirs)
install(TARGETS sipl_player
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})

# --validate compiles the player's graph for placeholder cameras and opens none, so these check on
# a runner with no camera that the graphs still compile: the HoloViz layers, the RAW path's tensor
# pools and the device bindings, which otherwise only fail once a camera is attached. They bind
# CUDA-device outputs, so a runner without a GPU can exclude them with `ctest -LE gpu`. With
# windows, --validate also checks that every HolovizOp has the same serial owner. The player prints
# the expected line only once validation passes; CTest still fails a run that crashes.
if(HOLOSCAN_CAMERA_BUILD_TESTING)
    function(add_sipl_player_validation name expected)
        add_test(NAME sipl_player_validate_${name}
            COMMAND $<TARGET_FILE:sipl_player> --validate ${ARGN})
        set_tests_properties(sipl_player_validate_${name} PROPERTIES
            PASS_REGULAR_EXPRESSION "graph validation complete \\(${expected}\\)"
            LABELS "plan;gpu")
    endfunction()
    add_sipl_player_validation(isp "isp, tiled")
    add_sipl_player_validation(raw "raw, tiled" --raw)
    add_sipl_player_validation(separate "isp, separate" --separate)
    add_sipl_player_validation(raw_separate "raw, separate" --raw --separate)
    add_sipl_player_validation(headless "isp, tiled, headless" --headless)
    add_sipl_player_validation(raw_separate_headless "raw, separate, headless"
        --raw --separate --headless)
endif()
