"""Verify the ESP32 sketch on Windows using the portable Sprint 6E toolchain."""

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
import re
import subprocess
import winreg


REPO = Path(__file__).resolve().parents[2]
PORTABLE = REPO / "ml/runtime/arduino6e"
RUNTIME = REPO / "ml/runtime/sprint7/firmware"
EVIDENCE = REPO / ".ai-context/SPRINT_7_FIRMWARE_EVIDENCE.json"
SOURCE = REPO / "firmware/esp32_scale"
SOURCE_NAMES = ("esp32_scale.ino", "scale_telemetry.h", "secrets.example.h")
INDEX = "https://espressif.github.io/arduino-esp32/package_esp32_index.json"
FQBN = "esp32:esp32:esp32"
DRIVE = "X:"


def run(command, *, env=None, timeout=90):
    return subprocess.run(
        [str(argument) for argument in command],
        cwd=REPO,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
    )


def result(process):
    combined = (process.stdout + process.stderr).strip()
    return {
        "return_code": process.returncode,
        "output": combined.replace(str(REPO), "<workspace>"),
    }


def windows_serial_ports():
    try:
        registry = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM")
    except FileNotFoundError:
        return []
    with registry:
        _, count, _ = winreg.QueryInfoKey(registry)
        return sorted({winreg.EnumValue(registry, index)[1] for index in range(count)})


def main():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    host_binary = RUNTIME / "esp32_scale_test.exe"
    host_command = [
        "g++", "-std=c++11", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic",
        "firmware/tests/esp32_scale_test.cpp", "-o", str(host_binary.relative_to(REPO)),
    ]
    host_build = run(host_command)
    host_test = run([host_binary]) if host_build.returncode == 0 else None
    print(f"Host compile exit {host_build.returncode}", flush=True)
    if host_test is not None:
        print(f"Host test exit {host_test.returncode}", flush=True)

    cli = PORTABLE / "arduino-cli.exe"
    mount = Path(f"{DRIVE}/")
    toolchain_env = {
        **os.environ,
        "ARDUINO_DIRECTORIES_DATA": str(mount / "data"),
        "ARDUINO_DIRECTORIES_DOWNLOADS": str(mount / "downloads"),
        "ARDUINO_DIRECTORIES_USER": str(mount / "user"),
        "ARDUINO_UPDATER_ENABLE_NOTIFICATION": "false",
    }
    sketch = mount / "sprint7/compile-fixture/esp32_scale"
    build_dir = mount / "sprint7/build"
    mount_result = run(["subst.exe", DRIVE, PORTABLE])
    if mount_result.returncode:
        raise RuntimeError(f"Could not map the portable toolchain to X: {result(mount_result)}")

    try:
        if not (mount / "arduino-cli.exe").is_file():
            raise RuntimeError("The X: mapping exists but the portable toolchain is inaccessible through it")
        sketch.mkdir(parents=True, exist_ok=True)
        sources = {name: (SOURCE / name).read_bytes() for name in SOURCE_NAMES}
        fixture = sources["secrets.example.h"].decode("utf-8")
        for marker, value in {
            "REPLACE_WITH_WIFI_SSID": "COMPILE_FIXTURE_NO_HARDWARE",
            "REPLACE_WITH_WIFI_PASSWORD": "compile-fixture-no-wifi",
            "LAN_IPV4": "192.168.4.10",
            "REPLACE_WITH_REGISTERED_DEVICE_KEY": "compile-fixture-xxxxxxxxxxxxxxxxxxxxxxxxxx",
        }.items():
            fixture = fixture.replace(marker, value)
        for name, contents in {**sources, "secrets.h": fixture.encode("utf-8")}.items():
            staged = sketch / name
            if not staged.is_file() or staged.read_bytes() != contents:
                staged.write_bytes(contents)

        cli_version = run([cli, "version"], env=toolchain_env)
        cores = run([cli, "core", "list", "--additional-urls", INDEX], env=toolchain_env)
        libraries = run([cli, "lib", "list"], env=toolchain_env)
        boards = run([cli, "board", "list", "--format", "json", "--discovery-timeout", "5s"],
                     env=toolchain_env)
        addresses = []
        if boards.returncode == 0:
            discovered = json.loads(boards.stdout).get("detected_ports") or []
            addresses = sorted({
                board["port"]["address"] for board in discovered
                if re.fullmatch(r"COM[0-9]+", board.get("port", {}).get("address", ""), re.IGNORECASE)
            })
        serial_ports = windows_serial_ports()
        print(f"Arduino COM ports {addresses}; Windows COM ports {serial_ports}", flush=True)

        target_command = [
            "compile", "--fqbn", FQBN, "--jobs", "8", "--additional-urls", INDEX,
            "--build-path", str(build_dir), str(sketch),
        ]
        print("Compiling ESP32 Dev Module with the isolated fixture", flush=True)
        target = run([cli, *target_command], env=toolchain_env, timeout=1500)
        print(f"Target compile exit {target.returncode}", flush=True)
        binary = build_dir / "esp32_scale.ino.bin"
        contents = binary.read_bytes() if target.returncode == 0 and binary.is_file() else b""
    finally:
        unmount = run(["subst.exe", DRIVE, "/d"])
        if unmount.returncode != 0:
            print(f"Temporary mapping cleanup failed: {result(unmount)}", flush=True)

    evidence = {
        "verified_at_utc": datetime.now(UTC).isoformat(),
        "host": {
            "compiler": run(["g++", "--version"]).stdout.splitlines()[0],
            "compile_command": host_command,
            "compile": result(host_build),
            "test_command": [str(host_binary.relative_to(REPO))],
            "test": result(host_test) if host_test is not None else None,
            "source_sha256": hashlib.sha256((REPO / "firmware/tests/esp32_scale_test.cpp").read_bytes()).hexdigest(),
        },
        "target": {
            "arduino_cli": result(cli_version),
            "core_list": result(cores),
            "library_list": result(libraries),
            "fqbn": FQBN,
            "compile_command": [str(cli.relative_to(REPO)), *target_command],
            "build_config": "Local compile fixture using invented settings",
            "compile": result(target),
            "source_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in sources.items()},
            "binary_bytes": len(contents) if contents else None,
            "binary_sha256": hashlib.sha256(contents).hexdigest() if contents else None,
            "temporary_drive_cleanup": result(unmount),
        },
        "hardware": {
            "arduino_board_list_exit_code": boards.returncode,
            "arduino_com_ports": addresses,
            "windows_com_ports": serial_ports,
            "physical_actions_performed": [],
        },
    }
    EVIDENCE.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Evidence written to {EVIDENCE.relative_to(REPO)}", flush=True)
    checks = (host_build, host_test, cli_version, cores, libraries, target, boards, unmount)
    return int(not contents or any(check is None or check.returncode for check in checks))


if __name__ == "__main__":
    raise SystemExit(main())
