# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Exercise container dependency selection without Docker, downloads, or a BSP."""

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"
CMAKE_LISTS = Path(__file__).resolve().parents[1] / "CMakeLists.txt"
WRAPPER = Path(__file__).resolve().parents[1] / "holoscan_camera"
SIPL_CMAKE_LISTS = (
    Path(__file__).resolve().parents[1]
    / "operators"
    / "sipl_capture_op"
    / "CMakeLists.txt"
)
SIPL_CAPTURE_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "operators"
    / "sipl_capture_op"
    / "sipl_capture_op.cpp"
)


class ContainerDependenciesTest(unittest.TestCase):
    def source_build_cmake_lists(self):
        # Wheel payload selection intentionally forces architecture-specific backends.
        # The BSP default/opt-in checks below describe ordinary source builds.
        return re.sub(
            r"(?ms)^if\(SKBUILD\)\n.*?^endif\(\)\n",
            "",
            CMAKE_LISTS.read_text(),
        )

    def run_argus_step(self, version):
        instructions = DOCKERFILE.read_text().replace("\\\n", "")
        step = next(
            match.group(1)
            for match in re.finditer(r"^RUN (.*)$", instructions, re.MULTILINE)
            if "install_argus_build_deps.sh" in match.group(1)
        )
        return subprocess.run(
            ["bash", "-c", 'bash() { printf "INSTALL %s\\n" "$*"; }; ' + step],
            env={
                **os.environ,
                "L4T_VERSION": version,
                "L4T_MAJ_VER": version.split(".")[0],
            },
            capture_output=True,
            text=True,
            check=False,
        )

    def test_r38_skips_argus_downloads(self):
        result = self.run_argus_step("38.5.0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Skipping Argus build dependencies", result.stdout)
        self.assertNotIn("INSTALL", result.stdout)

    def test_r39_installs_argus_dependencies(self):
        result = self.run_argus_step("39.2.0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "INSTALL /tmp/scripts/install_argus_build_deps.sh 39.2.0", result.stdout
        )

    def test_r38_warns_without_overriding_argus_options(self):
        cmake_lists = self.source_build_cmake_lists()
        self.assertIn(
            'file(STRINGS "/etc/nv_tegra_release" _l4t_release LIMIT_COUNT 1)',
            cmake_lists,
        )
        self.assertIn(
            'message(WARNING "Argus capture is not verified on IGX R38', cmake_lists
        )
        for target in ("APP_holoscan_camera_argus", "OP_argus_capture_op"):
            self.assertNotIn(f"set({target} OFF CACHE BOOL", cmake_lists)

    def run_sipl_step(self, version, curl_status=0):
        instructions = DOCKERFILE.read_text().replace("\\\n", "")
        step = next(
            match.group(1)
            for match in re.finditer(r"^RUN (.*)$", instructions, re.MULTILINE)
            if "Jetson_SIPL_API" in match.group(1)
        )
        # Shell functions intercept every external command in the SIPL step.
        # Even a host with an installed SIPL source tree cannot modify it.
        stubs = """
curl() { printf 'DOWNLOAD %s\\n' "$*"; return "$CURL_STATUS"; }
tar() { printf 'EXTRACT %s\\n' "$*"; }
rm() { :; }
cd() { :; }
mkdir() { :; }
cmake() { :; }
make() { :; }
nproc() { printf '1\\n'; }
"""
        return subprocess.run(
            ["bash", "-c", stubs + step],
            env={
                **os.environ,
                "L4T_VERSION": version,
                "L4T_MAJ_VER": version.split(".", 1)[0],
                "L4T_MIN_PATCH_VER": version.split(".", 1)[1],
                "CURL_STATUS": str(curl_status),
            },
            capture_output=True,
            text=True,
            check=False,
        )

    def test_igx_r38_v4l2_image_needs_no_sipl_download(self):
        result = self.run_sipl_step("38.5.0", curl_status=22)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Skipping SIPL API download for L4T 38.5.0", result.stdout)
        self.assertNotIn("DOWNLOAD", result.stdout)
        self.assertNotIn("EXTRACT", result.stdout)

    def test_supported_sipl_bsp_downloads_matching_archive(self):
        result = self.run_sipl_step("39.2.0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "https://developer.nvidia.com/downloads/embedded/L4T/"
            "r39_Release_v2.0/release/Jetson_SIPL_API_R39.2.0_aarch64.tbz2",
            result.stdout,
        )
        self.assertIn(
            "EXTRACT xjf Jetson_SIPL_API_R39.2.0_aarch64.tbz2 -C /", result.stdout
        )

    def test_supported_sipl_download_failure_still_fails_build(self):
        result = self.run_sipl_step("39.2.0", curl_status=22)
        self.assertEqual(result.returncode, 22, result.stderr)
        self.assertIn("DOWNLOAD", result.stdout)
        self.assertNotIn("EXTRACT", result.stdout)
        self.assertNotIn("SIPL API headers installed", result.stdout)

    def test_r38_cmake_defaults_sipl_off_but_preserves_explicit_opt_in(self):
        cmake_lists = self.source_build_cmake_lists()
        self.assertIn("L4T_MAJ_VER LESS 39", cmake_lists)
        for target in (
            "APP_sipl_frame_saver",
            "APP_sipl_stereo_monitor",
            "APP_sipl_player",
            "OP_sipl_capture_op",
        ):
            guard = (
                f"if(NOT PKG_holoscan_camera AND NOT DEFINED {target})"
                if target == "OP_sipl_capture_op"
                else f"if(NOT DEFINED {target})"
            )
            self.assertIn(guard, cmake_lists)
            self.assertRegex(cmake_lists, rf"set\({target} OFF CACHE BOOL [^\n]+\)")
            self.assertNotRegex(
                cmake_lists, rf"set\({target} OFF CACHE BOOL [^\n]+ FORCE\)"
            )

    def run_sipl_mount(
        self,
        *,
        headers=True,
        version="38.5.0",
        source_override=True,
        docker_opts=None,
        equals=False,
        target="sipl_frame_saver",
        command="build",
        local=False,
        container=False,
        build_args=None,
        default_build_args=None,
        passthrough=None,
    ):
        # Run the actual argument preparation and exec, substituting only host
        # files and the CLI executable. No bootstrap, Docker, or downloads run.
        wrapper = "CLI_ARGS=(" + WRAPPER.read_text().split("CLI_ARGS=(", 1)[1]
        with tempfile.TemporaryDirectory() as temporary_dir:
            temporary = Path(temporary_dir)
            root = temporary / "jetson_sipl_api"
            release_path = temporary / "nv_tegra_release"
            major, revision = version.split(".", 1)
            release_path.write_text(f"# R{major} (release), REVISION: {revision}\n")
            cli = temporary / "cli"
            cli.write_text(
                "#!/usr/bin/env bash\n"
                'printf "%s\\n" "$@"\n'
                'printf "BUILD_DEFAULTS=%s\\n" "${HOLOSCAN_CLI_DEFAULT_DOCKER_BUILD_ARGS:-}"\n'
            )
            cli.chmod(0o755)
            if headers:
                header = root / "sipl/include/NvSIPLCamera.hpp"
                header.parent.mkdir(parents=True)
                header.touch()

            wrapper = wrapper.replace("/etc/nv_tegra_release", str(release_path))
            wrapper = wrapper.replace(
                "${HOLOSCAN_CAMERA_SIPL_SOURCE_DIR:-/usr/src/jetson_sipl_api}",
                "${HOLOSCAN_CAMERA_SIPL_SOURCE_DIR:-" + str(root) + "}",
            )
            script = (
                "set -euo pipefail\n"
                + f"_is_container() {{ return {0 if container else 1}; }}\n"
                + wrapper
            )
            args = [command, target]
            if local:
                args.append("--local")
            if docker_opts is not None:
                args.extend(
                    [f"--docker-opts={docker_opts}"]
                    if equals
                    else ["--docker-opts", docker_opts]
                )
            if build_args is not None:
                args.extend(["--build-args", build_args])
            if passthrough is not None:
                args.extend(["--", *passthrough])
            env = os.environ.copy()
            env["PYTHON_BIN"] = str(cli)
            env.pop("HOLOSCAN_CLI_DEFAULT_DOCKER_BUILD_ARGS", None)
            if default_build_args is not None:
                env["HOLOSCAN_CLI_DEFAULT_DOCKER_BUILD_ARGS"] = default_build_args
            if source_override:
                env["HOLOSCAN_CAMERA_SIPL_SOURCE_DIR"] = str(root)
            else:
                env.pop("HOLOSCAN_CAMERA_SIPL_SOURCE_DIR", None)
            return subprocess.run(
                ["bash", "-c", script, "wrapper-test", *args],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

    def test_igx_r38_mounts_source_without_duplicating_mode_mounts(self):
        for equals in (False, True):
            with self.subTest(equals=equals):
                result = self.run_sipl_mount(docker_opts="--init", equals=equals)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("--init --mount=type=bind,src=", result.stdout)
                self.assertIn(
                    "dst=/opt/holoscan-camera/jetson_sipl_api,readonly", result.stdout
                )
                # The wrapper adds no device-tree mount: the SIPL apps' metadata runs
                # their containers privileged instead.
                self.assertNotIn("dst=/proc/device-tree", result.stdout)

    def test_igx_r38_mounts_default_source_for_module_tests(self):
        result = self.run_sipl_mount(source_override=False, target="holoscan-camera")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "dst=/opt/holoscan-camera/jetson_sipl_api,readonly", result.stdout
        )

    def test_igx_r38_rejects_invalid_explicit_source(self):
        result = self.run_sipl_mount(headers=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("SIPL source missing NvSIPLCamera.hpp", result.stderr)

    def test_run_container_mount_precedes_command_separator(self):
        result = self.run_sipl_mount(
            command="run-container",
            target="--no-docker-build",
            passthrough=["ctest", "--local", "--docker-opts=child-option"],
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        args = result.stdout.splitlines()
        mount_index = next(
            index
            for index, arg in enumerate(args)
            if arg.startswith("--docker-opts=--mount=")
        )
        self.assertLess(mount_index, args.index("--"))
        self.assertEqual(
            args[args.index("--") + 1 : args.index("--") + 4],
            ["ctest", "--local", "--docker-opts=child-option"],
        )

    def test_sipl_mount_exclusions(self):
        for options in (
            {"version": "39.2.1"},
            {"local": True},
            {"container": True},
            {"command": "list"},
            {"target": "holoscan_camera_v4l2", "source_override": False},
        ):
            with self.subTest(options=options):
                result = self.run_sipl_mount(**options)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn(
                    "dst=/opt/holoscan-camera/jetson_sipl_api", result.stdout
                )

    def test_r38_camera_package_mounts_default_sipl_source(self):
        result = self.run_sipl_mount(
            command="package", target="holoscan-camera", source_override=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "dst=/opt/holoscan-camera/jetson_sipl_api,readonly", result.stdout
        )

    def test_r38_unrelated_package_does_not_mount_default_sipl_source(self):
        result = self.run_sipl_mount(
            command="package", target="unrelated-package", source_override=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("dst=/opt/holoscan-camera/jetson_sipl_api", result.stdout)

    def test_missing_default_source_leaves_v4l2_independent(self):
        result = self.run_sipl_mount(headers=False, source_override=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("dst=/opt/holoscan-camera/jetson_sipl_api", result.stdout)

    def test_explicit_source_mounts_for_igx_v4l2_ci_command(self):
        result = self.run_sipl_mount(target="holoscan_camera_v4l2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("dst=/opt/holoscan-camera/jetson_sipl_api", result.stdout)

    def test_bsp_defaults_preserve_caller_build_arguments(self):
        result = self.run_sipl_mount(
            build_args="--network=host --build-arg L4T_VERSION=39.2.0",
            default_build_args="--build-arg CUSTOM=value",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "BUILD_DEFAULTS=--build-arg L4T_VERSION=38.5.0 --build-arg CUSTOM=value",
            result.stdout,
        )
        self.assertIn(
            "--build-args\n--network=host --build-arg L4T_VERSION=39.2.0\n",
            result.stdout,
        )
        self.assertEqual(result.stdout.count("--build-args\n"), 1)

    def test_sipl_v1_uses_archive_layout_and_guards_v2_metadata(self):
        cmake_lists = SIPL_CMAKE_LISTS.read_text()
        source = SIPL_CAPTURE_SOURCE.read_text()
        self.assertIn(
            'if(EXISTS "${NVSIPL_INCLUDE_DIR}/query/include/NvSIPLCameraQuery.hpp")',
            cmake_lists,
        )
        self.assertRegex(
            source,
            r"#if SIPL_V2\s*"
            r"frame_dropped = frame_dropped \|\| img_meta\.wasFrameDropped;",
        )


if __name__ == "__main__":
    unittest.main()
