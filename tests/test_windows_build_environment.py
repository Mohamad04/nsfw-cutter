"""The Windows build bundles the same dependencies whatever shell launches it (scripts/build_windows.ps1).

PyInstaller resolves DLLs it cannot find next to the collected binaries through PATH, and its PySide6 hook
bundles the OpenSSL that Qt finds there. Git Bash puts Git for Windows' libssl-3-x64.dll on PATH and
ImageMagick ships its own VC++ runtime, so the build runs PyInstaller with a fixed, Windows-only PATH.
"""

import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "scripts" / "build_windows.ps1"
INTERNAL = ROOT / "dist" / "VideoCutter" / "_internal"
COLLECT_TOC = ROOT / "build" / "VideoCutter" / "COLLECT-00.toc"
SYSTEM_ROOT = os.environ.get("SystemRoot", r"C:\Windows")
CONTROLLED_PATH = os.pathsep.join(
    [os.path.join(SYSTEM_ROOT, "System32"), SYSTEM_ROOT, os.path.join(SYSTEM_ROOT, "System32", "Wbem")]
)
GIT_OPENSSL_DIR = Path(r"C:\Program Files\Git\mingw64\bin")
PYTHON_DLLS = Path(sys.base_prefix) / "DLLs"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _importable(*modules: str) -> bool:
    try:
        for module in modules:
            __import__(module)
    except ImportError:
        return False
    return True


def _run_with_path(path: str, code: str) -> dict:
    env = {**os.environ, "PATH": path}
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=300)
    if completed.returncode != 0:
        raise AssertionError(completed.stderr[-3000:])
    return json.loads(completed.stdout.strip().splitlines()[-1])


_PYINSTALLER_SELECTION = """
import json
from PyInstaller.depend import bindepend
from PyInstaller.utils.hooks.qt import pyside6_library_info
print(json.dumps({
    'qt_openssl': [src for src, _dest in pyside6_library_info.collect_qtnetwork_files()],
    'path_fallback': {name: bindepend.resolve_library_path(name, []) for name in (
        'msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'libssl-3-x64.dll', 'libcrypto-3-x64.dll')},
}))
"""

_PYTHON_SSL = """
import hashlib, json, ssl
context = ssl.create_default_context()
print(json.dumps({'version': ssl.OPENSSL_VERSION, 'verify': context.verify_mode == ssl.CERT_REQUIRED,
                  'sha256': hashlib.sha256(b'abc').hexdigest()}))
"""

_QT_TLS = """
import json
from PySide6.QtCore import QCoreApplication
from PySide6.QtNetwork import QSslSocket
app = QCoreApplication([])
print(json.dumps({'supports': QSslSocket.supportsSsl(), 'available': QSslSocket.availableBackends(),
                  'active': QSslSocket.activeBackend()}))
"""


class BuildScriptEnvironmentTests(unittest.TestCase):
    def test_pyinstaller_runs_with_a_fixed_windows_only_path(self):
        text = BUILD.read_text(encoding="utf-8")
        start = text.index("$controlledBuildPath = @(")
        construction = text[start:text.index(') -join ";"', start)]
        for entry in ('(Join-Path $env:SystemRoot "System32")', "$env:SystemRoot",
                      '(Join-Path $env:SystemRoot "System32\\Wbem")'):
            self.assertIn(entry, construction)
        self.assertNotIn("$env:PATH", construction)
        set_path = text.index("$env:PATH = $controlledBuildPath")
        self.assertLess(set_path, text.index("& $pythonExe -m PyInstaller @pyinstallerArgs"))
        self.assertGreater(text.index("$env:PATH = $originalPath"), set_path)
        self.assertIn("$pythonExe = (Get-Command $pythonExe -ErrorAction Stop).Source", text)

    def test_post_build_checks_reject_foreign_openssl_and_foreign_sources(self):
        text = BUILD.read_text(encoding="utf-8")
        self.assertIn("Unexpected OpenSSL libraries in the PyInstaller output", text)
        self.assertIn("'^(lib(ssl|crypto)|libeay32|ssleay32)'", text)
        self.assertIn('foreach ($sslModule in @("_ssl.pyd", "_hashlib.pyd"))', text)
        self.assertIn("differs from $($pythonDll.FullName)", text)
        self.assertIn("Files collected from outside the project, Python and Windows", text)
        self.assertIn("$collectToc $ProjectRoot $pythonPrefix $pythonBasePrefix $env:SystemRoot", text)


@unittest.skipUnless(sys.platform == "win32" and _importable("PyInstaller", "PySide6.QtNetwork"),
                     "Windows with PyInstaller and PySide6 is required")
class ControlledPathBehaviourTests(unittest.TestCase):
    def test_controlled_path_selects_no_qt_openssl_and_the_system_vc_runtime(self):
        selected = _run_with_path(CONTROLLED_PATH, _PYINSTALLER_SELECTION)
        self.assertEqual(selected["qt_openssl"], [])
        self.assertIsNone(selected["path_fallback"]["libssl-3-x64.dll"])
        self.assertIsNone(selected["path_fallback"]["libcrypto-3-x64.dll"])
        for name in ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"):
            source = selected["path_fallback"][name]
            self.assertIsNotNone(source, name)
            self.assertEqual(Path(source).parent.resolve(), Path(SYSTEM_ROOT, "System32").resolve(), name)

    @unittest.skipUnless((GIT_OPENSSL_DIR / "libssl-3-x64.dll").is_file(), "Git for Windows OpenSSL is not installed")
    def test_git_openssl_on_the_inherited_path_would_be_bundled(self):
        # The hazard the fixed PATH removes: the same hook picks Git's OpenSSL as soon as it is on PATH.
        selected = _run_with_path(os.pathsep.join([str(GIT_OPENSSL_DIR), CONTROLLED_PATH]), _PYINSTALLER_SELECTION)
        self.assertEqual({Path(p).parent for p in selected["qt_openssl"]}, {GIT_OPENSSL_DIR})

    def test_python_ssl_works_with_the_controlled_path(self):
        python_ssl = _run_with_path(CONTROLLED_PATH, _PYTHON_SSL)
        self.assertTrue(python_ssl["version"].startswith("OpenSSL 3."), python_ssl)
        self.assertTrue(python_ssl["verify"])
        self.assertEqual(python_ssl["sha256"], hashlib.sha256(b"abc").hexdigest())

    def test_qt_tls_uses_schannel_with_the_controlled_path(self):
        qt_tls = _run_with_path(CONTROLLED_PATH, _QT_TLS)
        self.assertTrue(qt_tls["supports"])
        self.assertIn("schannel", qt_tls["available"])
        self.assertNotIn("openssl", qt_tls["available"])


class BuiltPackageTests(unittest.TestCase):
    def setUp(self):
        if not (INTERNAL / "_ssl.pyd").is_file():
            self.skipTest("dist/VideoCutter is not built (run scripts/build_windows.ps1)")

    def test_only_pythons_openssl_is_bundled_and_unchanged(self):
        python_openssl = sorted(p for p in PYTHON_DLLS.glob("lib*.dll") if p.name.startswith(("libssl-", "libcrypto-")))
        self.assertEqual(len(python_openssl), 2)
        for dll in python_openssl:
            self.assertEqual(_sha256(INTERNAL / dll.name), _sha256(dll), dll.name)
        self.assertTrue((INTERNAL / "_hashlib.pyd").is_file())
        bundled = sorted(p.relative_to(INTERNAL).as_posix() for p in INTERNAL.rglob("*")
                         if p.is_file() and p.name.lower().startswith(("libssl", "libcrypto", "libeay32", "ssleay32")))
        self.assertEqual(bundled, sorted(dll.name for dll in python_openssl))

    def test_qt_tls_plugins_remain_bundled(self):
        tls = INTERNAL / "PySide6" / "plugins" / "tls"
        for plugin in ("qschannelbackend.dll", "qcertonlybackend.dll", "qopensslbackend.dll"):
            self.assertTrue((tls / plugin).is_file(), plugin)

    def test_collected_files_come_from_the_project_python_or_windows(self):
        if not COLLECT_TOC.is_file():
            self.skipTest("build/VideoCutter/COLLECT-00.toc is not available")
        import ast
        toc = ast.literal_eval(COLLECT_TOC.read_text(encoding="utf-8"))
        entries = next(part for part in toc if isinstance(part, list) and part and isinstance(part[0], tuple))
        roots = tuple(os.path.normcase(os.path.abspath(root)).rstrip(os.sep) + os.sep
                      for root in (ROOT, sys.prefix, sys.base_prefix, SYSTEM_ROOT))
        outside = sorted({src for _dest, src, _kind in entries
                          if src and not os.path.normcase(os.path.abspath(src)).startswith(roots)})
        self.assertEqual(outside, [])

    def test_cuda_runtimes_and_ffmpeg_are_unchanged(self):
        cublas_pin = json.loads((ROOT / "scripts" / "cuda12-cublas-pin.json").read_text(encoding="utf-8"))
        for name, binary in cublas_pin["binaries"].items():
            self.assertEqual(sorted(INTERNAL.rglob(name)), [INTERNAL / "ctranslate2" / name], name)
            self.assertEqual((INTERNAL / "ctranslate2" / name).stat().st_size, binary["size"], name)
        for name in ("cublas64_13.dll", "cublasLt64_13.dll", "cudart64_13.dll"):
            self.assertTrue((INTERNAL / "torch" / "lib" / name).is_file(), name)
        ffmpeg_pin = json.loads((ROOT / "scripts" / "ffmpeg-pin.json").read_text(encoding="utf-8"))
        for name, digest in ffmpeg_pin["binaries"].items():
            self.assertEqual(_sha256(INTERNAL / "vendor" / "ffmpeg" / "bin" / name), digest, name)


if __name__ == "__main__":
    unittest.main()
