"""Write deterministic archives, standalone installers and checksum reports."""
from __future__ import annotations

import gzip
import hashlib
import io
import json
from pathlib import Path
import stat
import tarfile
import zipfile


def write_artifacts(output: Path, version: str, commit: str | None,
                    files: dict[str, bytes], bootstraps: dict[str, bytes]) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    artifact = output / f"harness-codex-{version}-linux.tar.gz"
    content = io.BytesIO()
    with tarfile.open(fileobj=content, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, data in sorted(files.items()):
            info = tarfile.TarInfo(f"harness-codex-{version}/{name}")
            info.size = len(data)
            info.mode = 0o755 if name in {"install.sh", "harness.py"} else 0o644
            info.mtime = 0
            archive.addfile(info, io.BytesIO(data))
    with artifact.open("xb") as stream:
        with gzip.GzipFile(fileobj=stream, filename="", mode="wb", mtime=0) as compressed:
            compressed.write(content.getvalue())
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    bootstrap = output / "install_harness_codex.sh"
    with bootstrap.open("xb") as stream:
        stream.write(bootstraps["install_harness_codex.sh"])
    bootstrap.chmod(0o755)
    bootstrap_digest = hashlib.sha256(bootstraps["install_harness_codex.sh"]).hexdigest()
    windows = output / f"harness-codex-{version}-windows.zip"
    with zipfile.ZipFile(windows, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(f"harness-codex-{version}/{name}", date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    windows_digest = hashlib.sha256(windows.read_bytes()).hexdigest()
    windows_bootstrap = output / "install_harness_codex.ps1"
    windows_bootstrap.write_bytes(bootstraps[windows_bootstrap.name])
    windows_bootstrap_digest = hashlib.sha256(windows_bootstrap.read_bytes()).hexdigest()
    with (output / "SHA256SUMS").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(f"{digest}  {artifact.name}\n{bootstrap_digest}  {bootstrap.name}\n{windows_digest}  {windows.name}\n{windows_bootstrap_digest}  {windows_bootstrap.name}\n")
    report = {"runtime": "codex", "version": version, "commit": commit, "developmentBuild": commit is None,
              "artifact": str(artifact), "sha256": digest, "bootstrapSha256": bootstrap_digest, "windowsArtifact": str(windows), "windowsSha256": windows_digest,
              "windowsBootstrapSha256": windows_bootstrap_digest, "files": len(files)}
    with (output / "build.json").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(report, indent=2) + "\n")
    return report
