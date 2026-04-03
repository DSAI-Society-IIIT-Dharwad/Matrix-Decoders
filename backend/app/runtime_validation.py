from __future__ import annotations

import importlib.util
import subprocess
import sys
from dataclasses import asdict, dataclass, field

from .config import existing_env_files, settings
from .tts_router import tts_router


REQUIRED_RUNTIME_PACKAGES = (
    "fastapi",
    "httpx",
    "websockets",
    "whisper",
    "torch",
    "torchaudio",
    "transformers",
)

OPTIONAL_RUNTIME_PACKAGES = (
    "TTS",
    "sounddevice",
)


@dataclass
class ValidationIssue:
    level: str
    message: str


@dataclass
class RuntimeValidationReport:
    python_version: str
    env_files: list[str]
    settings_summary: dict[str, object]
    required_packages: dict[str, bool]
    optional_packages: dict[str, bool]
    tts_providers: list[dict]
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(issue.level == "error" for issue in self.issues)

    def as_dict(self) -> dict[str, object]:
        return {
            "python_version": self.python_version,
            "env_files": self.env_files,
            "settings_summary": self.settings_summary,
            "required_packages": self.required_packages,
            "optional_packages": self.optional_packages,
            "tts_providers": self.tts_providers,
            "issues": [asdict(issue) for issue in self.issues],
            "has_errors": self.has_errors,
        }


def _package_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _probe_python_module(python_bin: str, module_name: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            [python_bin, "-c", f"import {module_name}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except Exception as exc:
        return False, str(exc)

    if result.returncode == 0:
        return True, ""

    stderr = (result.stderr or result.stdout or "").strip()
    return False, stderr or f"Failed to import {module_name}"


def collect_runtime_validation_report(run_command_probes: bool = False) -> RuntimeValidationReport:
    required_packages = {
        package_name: _package_available(package_name)
        for package_name in REQUIRED_RUNTIME_PACKAGES
    }
    optional_packages = {
        package_name: _package_available(package_name)
        for package_name in OPTIONAL_RUNTIME_PACKAGES
    }

    report = RuntimeValidationReport(
        python_version=sys.version.replace("\n", " "),
        env_files=[str(path) for path in existing_env_files()],
        settings_summary={
            "ollama_base_url": settings.ollama_base_url,
            "ollama_model": settings.ollama_model,
            "enable_tts": settings.enable_tts,
            "enable_tts_fallback_tone": settings.enable_tts_fallback_tone,
            "tts_sample_rate": settings.tts_sample_rate,
        },
        required_packages=required_packages,
        optional_packages=optional_packages,
        tts_providers=tts_router.provider_diagnostics(),
    )

    if not report.env_files:
        report.issues.append(
            ValidationIssue(
                level="warning",
                message="No .env file was found in backend/.env or repo-root .env.",
            )
        )

    for package_name, is_available in required_packages.items():
        if not is_available:
            report.issues.append(
                ValidationIssue(
                    level="error",
                    message=f"Required runtime package is missing: {package_name}",
                )
            )

    if settings.enable_tts:
        if not tts_router.available_providers():
            report.issues.append(
                ValidationIssue(
                    level="error",
                    message="TTS is enabled but no provider is currently available.",
                )
            )

        if not tts_router.available_real_speech_providers():
            report.issues.append(
                ValidationIssue(
                    level="warning",
                    message=(
                        "No real speech TTS provider is available yet. "
                        "Tone fallback will be used until AI4Bharat, Piper, or Coqui is configured."
                    ),
                )
            )

        for diagnostic in report.tts_providers:
            for issue in diagnostic.get("issues", []):
                report.issues.append(
                    ValidationIssue(
                        level="warning",
                        message=f"{diagnostic['name']}: {issue}",
                    )
                )

    if run_command_probes and settings.enable_tts:
        ok, message = _probe_python_module(settings.indic_tts_python_bin or "python", "TTS")
        if not ok:
            report.issues.append(
                ValidationIssue(
                    level="warning",
                    message=(
                        "The configured Indic-TTS python binary could not import TTS: "
                        f"{message}"
                    ),
                )
            )

    return report
