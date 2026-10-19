"""CTranslate2 (faster-whisper) GPU inference uses a pinned CUDA 12 cuBLAS (scripts/cuda12-cublas-pin.json).

These checks never download the NVIDIA archive: the vendor and dist checks are skipped when the
files have not been prepared or built locally.
"""

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN_PATH = ROOT / "scripts" / "cuda12-cublas-pin.json"
PIN = json.loads(PIN_PATH.read_text(encoding="utf-8"))
PREPARE = ROOT / "scripts" / "prepare_cuda12_cublas.ps1"
BUILD = ROOT / "scripts" / "build_windows.ps1"
VENDOR = ROOT / "vendor" / "cuda12-cublas"
INTERNAL = ROOT / "dist" / "VideoCutter" / "_internal"
CUBLAS_NAMES = {"cublas64_12.dll", "cublasLt64_12.dll"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _powershell() -> str | None:
    return shutil.which("powershell") if sys.platform == "win32" else None


class CublasPinTests(unittest.TestCase):
    def test_pin_describes_one_nvidia_redistributable_with_both_dlls(self):
        self.assertEqual(PIN["version"], "12.8.4.1")
        self.assertEqual(set(PIN["binaries"]), CUBLAS_NAMES)
        for name, binary in PIN["binaries"].items():
            self.assertRegex(binary["sha256"], r"^[0-9a-f]{64}$", name)
            self.assertGreater(binary["size"], 0, name)
            self.assertEqual(binary["archive_path"], f"bin/{name}")
        self.assertRegex(PIN["archive_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(PIN["archive_size"], 563660944)
        self.assertEqual(PIN["documents"]["LICENSE"]["target"], "LICENSE.txt")
        self.assertRegex(PIN["documents"]["LICENSE"]["sha256"], r"^[0-9a-f]{64}$")

    def test_archive_source_is_the_pinned_official_nvidia_redistributable(self):
        prefix = "https://developer.download.nvidia.com/compute/cuda/redist/"
        self.assertEqual(
            PIN["download_url"],
            prefix + "libcublas/windows-x86_64/libcublas-windows-x86_64-12.8.4.1-archive.zip",
        )
        self.assertEqual(PIN["manifest_url"], prefix + "redistrib_12.8.1.json")
        self.assertEqual(PIN["archive_name"], PIN["download_url"].rsplit("/", 1)[1])
        self.assertEqual(PIN["archive_root"], PIN["archive_name"].removesuffix(".zip"))
        self.assertNotIn("latest", PIN["download_url"])

    def test_only_cuda12_dlls_are_pinned_and_cudnn_is_not_bundled(self):
        for name in PIN["binaries"]:
            self.assertTrue(name.endswith("64_12.dll"), name)
            self.assertNotIn("cudnn", name.lower())

    def test_preparation_script_downloads_only_with_explicit_authorization(self):
        text = PREPARE.read_text(encoding="utf-8")
        self.assertIn("cuda12-cublas-pin.json", text)
        self.assertIn("[switch]$AllowDownload", text)
        self.assertIn("[string]$ArchivePath", text)
        self.assertEqual(text.count("Invoke-WebRequest"), 1)
        download_branch = text[text.index("} elseif ($AllowDownload) {"):]
        self.assertIn("Invoke-WebRequest -Uri $pin.download_url", download_branch.split("} else {", 1)[0])
        self.assertIn("downloading is not allowed", text)
        self.assertNotIn("PATH", text.replace("never changes PATH", ""))

    def test_build_bundles_both_dlls_beside_ctranslate2_and_verifies_them(self):
        text = BUILD.read_text(encoding="utf-8")
        self.assertEqual(PIN["bundle_destination"], "ctranslate2")
        self.assertIn("prepare_cuda12_cublas.ps1", text)
        self.assertIn('"--add-binary", "$(Join-Path $cublasVendorDir $cublasName);$($cublasPin.bundle_destination)"', text)
        self.assertIn("is not the pinned cuBLAS", text)
        self.assertIn("The NVIDIA cuBLAS license text is missing", text)

    def test_build_removes_the_top_level_duplicate_and_requires_a_single_copy(self):
        text = BUILD.read_text(encoding="utf-8")
        self.assertIn("$topLevelCopy = Join-Path $internalDir $cublasName", text)
        self.assertIn("-eq $cublasPin.binaries.$cublasName.sha256", text)
        self.assertIn("Unexpected extra copies of", text)

    def test_build_ships_the_license_and_pin_under_vendor(self):
        text = BUILD.read_text(encoding="utf-8")
        self.assertIn('@($cublasPin.documents.LICENSE.target, "BUILD-PIN.json")', text)
        self.assertIn('"$(Join-Path $cublasVendorDir $cublasDocument);vendor\\cuda12-cublas"', text)

    def test_build_does_not_touch_the_pytorch_cuda13_libraries(self):
        text = BUILD.read_text(encoding="utf-8")
        for forbidden in ("_13.dll", "torch\\lib", "cudnn", "add_dll_directory"):
            self.assertNotIn(forbidden, text)
        # The build may restrict PATH for PyInstaller, but never puts the CUDA 12 DLLs on it.
        for line in text.splitlines():
            if "$env:PATH" in line or "controlledBuildPath" in line:
                self.assertNotIn("cublas", line.lower())
                self.assertNotIn("vendor", line.lower())

    @unittest.skipUnless(_powershell(), "Windows PowerShell is required")
    def test_preparation_refuses_without_a_source_and_rejects_a_wrong_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            command = [_powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(PREPARE),
                       "-ProjectRoot", tmp]
            refused = subprocess.run(command, capture_output=True, text=True, timeout=120)
            self.assertEqual(refused.returncode, 1)
            self.assertIn("downloading is not allowed", refused.stderr)

            fake = Path(tmp) / PIN["archive_name"]
            fake.write_bytes(b"not the NVIDIA archive")
            rejected = subprocess.run([*command, "-ArchivePath", str(fake)], capture_output=True, text=True,
                                      timeout=120)
            self.assertEqual(rejected.returncode, 1)
            self.assertIn(f"expected {PIN['archive_size']}", rejected.stderr)
            self.assertFalse((Path(tmp) / "vendor" / "cuda12-cublas" / "cublas64_12.dll").exists())

    def test_project_local_cublas_is_the_pinned_build_with_its_license(self):
        if not (VENDOR / "cublas64_12.dll").is_file():
            self.skipTest("vendor/cuda12-cublas is not prepared (run scripts/prepare_cuda12_cublas.ps1)")
        for name, binary in PIN["binaries"].items():
            self.assertEqual((VENDOR / name).stat().st_size, binary["size"], name)
            self.assertEqual(_sha256(VENDOR / name), binary["sha256"], name)
        self.assertEqual(_sha256(VENDOR / "LICENSE.txt"), PIN["documents"]["LICENSE"]["sha256"])

    def test_built_package_keeps_cuda12_beside_ctranslate2_and_cuda13_in_torch(self):
        if not (INTERNAL / "ctranslate2" / "ctranslate2.dll").is_file():
            self.skipTest("dist/VideoCutter is not built (run scripts/build_windows.ps1)")
        for name, binary in PIN["binaries"].items():
            copies = sorted(INTERNAL.rglob(name))
            self.assertEqual(copies, [INTERNAL / "ctranslate2" / name], name)
            self.assertEqual(copies[0].stat().st_size, binary["size"], name)
        self.assertEqual(_sha256(INTERNAL / "vendor" / "cuda12-cublas" / "LICENSE.txt"),
                         PIN["documents"]["LICENSE"]["sha256"])
        for name in ("cublas64_13.dll", "cublasLt64_13.dll"):
            self.assertTrue((INTERNAL / "torch" / "lib" / name).is_file(), name)
            self.assertEqual(sorted(p.parent.name for p in INTERNAL.rglob(name)), ["lib"], name)


if __name__ == "__main__":
    unittest.main()
