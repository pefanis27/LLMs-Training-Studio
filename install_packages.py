from __future__ import annotations

import argparse
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable

# ============================================================
# install_packages_full_verified.py
# Πλήρες script εγκατάστασης πακέτων για το LLM Training Studio
# - Καλύπτει GUI + training/inference + runtime εξαρτήσεις
# - Υποστηρίζει προαιρετική CUDA-aware εγκατάσταση του torch
# - Κάνει verify των βασικών imports μετά την εγκατάσταση
# - Κάνει προαιρετικό py_compile check στο κύριο αρχείο της εφαρμογής
# ============================================================

SCRIPT_DIR = Path(__file__).resolve().parent
LOG_FILE = SCRIPT_DIR / "install_packages.log"

APP_CANDIDATES = [
    "LLM_Training_Studio.py",
    "LLM_Training_Studio_NEW_LAST.py",
    "LLM_Training_Studio_NEW_LAST_stage_split_fixed.py",
    "LLM_Training_Studio_NEW_LAST_mixed_eval_completed.py",
]

GUI_REQUIRED_PACKAGES = [
    "PySide6",
    "huggingface_hub",
]

# Το torch εγκαθίσταται ξεχωριστά, ώστε να υποστηρίζει CPU/CUDA index επιλογή.
PIPELINE_REQUIRED_PACKAGES = [
    "transformers",
    "datasets",
    "accelerate",
    "peft",
    "trl",
    "python-docx",
    "openpyxl",
    "pandas",
]

RUNTIME_DEPENDENCY_PACKAGES = [
    "sentencepiece",
    "safetensors",
    "protobuf",
]

TORCH_INDEX_URLS = {
    "cpu": "https://download.pytorch.org/whl/cpu",
    "cu129": "https://download.pytorch.org/whl/cu129",
    "cu128": "https://download.pytorch.org/whl/cu128"
}

VERIFY_IMPORTS_GUI = [
    (
        "PySide6 core/gui/widgets + QShortcut",
        "from PySide6.QtCore import QObject, QThread, Qt, Signal, QTimer, QEvent, QUrl; "
        "from PySide6.QtGui import QAction, QColor, QDesktopServices, QKeySequence, QPainter, "
        "QPen, QFont, QShortcut, QTextCursor, QTextOption; "
        "from PySide6.QtWidgets import QApplication, QWidget, QMessageBox",
    ),
    ("huggingface_hub", "from huggingface_hub import HfApi, snapshot_download, get_token"),
]

VERIFY_IMPORTS_PIPELINE = [
    ("torch", "import torch; print(torch.__version__)"),
    (
        "transformers core objects",
        "from transformers import AutoTokenizer, AutoModelForCausalLM, TextIteratorStreamer, StoppingCriteriaList",
    ),
    ("datasets.Dataset", "from datasets import Dataset"),
    ("accelerate", "import accelerate"),
    ("peft", "from peft import LoraConfig, PeftModel, TaskType, get_peft_model"),
    ("trl", "from trl import SFTTrainer, SFTConfig"),
    ("python-docx", "import docx"),
    ("openpyxl", "from openpyxl import load_workbook"),
    ("pandas", "import pandas as pd"),
]

VERIFY_IMPORTS_RUNTIME = [
    ("sentencepiece", "import sentencepiece"),
    ("safetensors", "import safetensors"),
    ("protobuf", "import google.protobuf"),
]


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def log(message: str = "") -> None:
    line = f"[{now()}] {message}"
    print(line)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def render_command(command: Iterable[str]) -> str:
    return " ".join(f'"{part}"' if " " in part else part for part in command)


def run_command(command: list[str], description: str, dry_run: bool = False) -> int:
    log(f"▶ {description}")
    log(f"$ {render_command(command)}")

    if dry_run:
        log("ℹ Dry-run: δεν εκτελέστηκε εντολή.")
        return 0

    try:
        completed = subprocess.run(command, check=False)
    except Exception as exc:
        log(f"✗ Σφάλμα κατά την εκτέλεση: {description} -> {exc}")
        return 1

    if completed.returncode == 0:
        log(f"✓ Επιτυχία: {description}")
    else:
        log(f"✗ Αποτυχία: {description} (κωδικός εξόδου {completed.returncode})")
    return completed.returncode


def run_inline_python(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
    )


def detect_app_file(explicit_path: str | None = None) -> Path | None:
    if explicit_path:
        candidate = Path(explicit_path).expanduser().resolve()
        return candidate if candidate.exists() else None

    for name in APP_CANDIDATES:
        candidate = SCRIPT_DIR / name
        if candidate.exists():
            return candidate
    return None


def upgrade_core_tools(dry_run: bool) -> int:
    return run_command(
        [sys.executable, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"],
        "Αναβάθμιση pip / setuptools / wheel",
        dry_run=dry_run,
    )


def install_package_group(
    packages: list[str],
    label: str,
    upgrade: bool,
    dry_run: bool,
) -> int:
    if not packages:
        return 0

    command = [sys.executable, "-m", "pip", "install"]
    if upgrade:
        command.append("--upgrade")
    command.extend(packages)
    return run_command(
        command,
        f"Εγκατάσταση {label} ({len(packages)}): {', '.join(packages)}",
        dry_run=dry_run,
    )


def install_torch(
    torch_variant: str,
    torch_index_url: str | None,
    upgrade: bool,
    dry_run: bool,
) -> int:
    command = [sys.executable, "-m", "pip", "install"]
    if upgrade:
        command.append("--upgrade")
    command.append("torch")

    effective_index = torch_index_url
    if effective_index is None and torch_variant in TORCH_INDEX_URLS:
        effective_index = TORCH_INDEX_URLS[torch_variant]

    description = f"Εγκατάσταση torch (variant={torch_variant})"
    if effective_index:
        command.extend(["--index-url", effective_index])
        description += f" με index-url={effective_index}"
    else:
        description += " από το προεπιλεγμένο PyPI index"

    return run_command(command, description, dry_run=dry_run)


def verify_imports(selected_checks: list[tuple[str, str]], dry_run: bool) -> int:
    if dry_run:
        log("ℹ Παράλειψη verify imports λόγω dry-run.")
        return 0

    log("\n--- Verify imports ---")
    failed = 0
    for label, code in selected_checks:
        log(f"▶ Verify: {label}")
        completed = run_inline_python(code)
        if completed.returncode == 0:
            version_info = completed.stdout.strip()
            if version_info:
                log(f"✓ OK: {label} | {version_info}")
            else:
                log(f"✓ OK: {label}")
            continue

        failed += 1
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        details = stderr or stdout or "Άγνωστο σφάλμα import"
        log(f"✗ Αποτυχία verify: {label}")
        log(f"  {details}")

    if failed == 0:
        log("✓ Όλα τα επιλεγμένα imports πέρασαν επιτυχώς.")
        return 0

    log(f"✗ Αποτυχίες verify imports: {failed}")
    return 1


def compile_check_app(app_file: Path | None, dry_run: bool) -> int:
    if app_file is None:
        log("⚠ Δεν βρέθηκε αρχείο εφαρμογής για compile check. Παραλείπεται.")
        return 0

    if dry_run:
        log(f"ℹ Παράλειψη py_compile check λόγω dry-run: {app_file}")
        return 0

    return run_command(
        [sys.executable, "-m", "py_compile", str(app_file)],
        f"Py-compile έλεγχος κύριου αρχείου εφαρμογής: {app_file}",
        dry_run=False,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Πλήρης εγκατάσταση πακέτων για το LLM Training Studio.\n\n"
            "Προεπιλογή: εγκαθιστά GUI + pipeline + runtime εξαρτήσεις και κάνει verify imports.\n"
            "Για ελάχιστη εγκατάσταση GUI μόνο, χρησιμοποίησε --gui-only."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--gui-only",
        action="store_true",
        help="Εγκαθιστά μόνο τα βασικά GUI πακέτα.",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Συμβατό alias για πλήρη εγκατάσταση της εφαρμογής.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Συμβατό alias για πλήρη εγκατάσταση της εφαρμογής.",
    )
    parser.add_argument(
        "--with-runtime",
        action="store_true",
        help="Συμβατό flag. Η πλήρης εγκατάσταση περιλαμβάνει ήδη runtime εξαρτήσεις.",
    )
    parser.add_argument(
        "--no-runtime",
        action="store_true",
        help="Παραλείπει τις runtime εξαρτήσεις (sentencepiece, safetensors, protobuf).",
    )
    parser.add_argument(
        "--torch-variant",
        choices=["default", "cpu", "cu118", "cu121", "cu124"],
        default="default",
        help=(
            "Τρόπος εγκατάστασης του torch."
            " 'default' = απλό pip install torch,"
            " αλλιώς χρησιμοποιείται το αντίστοιχο PyTorch index-url."
        ),
    )
    parser.add_argument(
        "--torch-index-url",
        default=None,
        help="Προσαρμοσμένο index-url για torch. Αν δοθεί, υπερισχύει του --torch-variant.",
    )
    parser.add_argument(
        "--app-file",
        default=None,
        help="Ρητή διαδρομή του κύριου .py αρχείου της εφαρμογής για compile check.",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Παράλειψη verify imports μετά την εγκατάσταση.",
    )
    parser.add_argument(
        "--skip-compile-check",
        action="store_true",
        help="Παράλειψη py_compile ελέγχου του κύριου αρχείου της εφαρμογής.",
    )
    parser.add_argument(
        "--no-upgrade-tools",
        action="store_true",
        help="Να μη γίνει αναβάθμιση των pip / setuptools / wheel.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Εμφανίζει τι θα εγκατασταθεί χωρίς να εκτελέσει εντολές.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # Συμβατότητα παλιών σημαιών.
    full_install = not args.gui_only
    if args.full or args.all:
        full_install = True

    include_runtime = full_install and not args.no_runtime
    app_file = detect_app_file(args.app_file)

    verify_checks = list(VERIFY_IMPORTS_GUI)
    if full_install:
        verify_checks.extend(VERIFY_IMPORTS_PIPELINE)
    if include_runtime:
        verify_checks.extend(VERIFY_IMPORTS_RUNTIME)

    log("=" * 90)
    log("Εκκίνηση install_packages_full_verified.py")
    log(f"Python executable : {sys.executable}")
    log(f"Python version    : {sys.version.split()[0]}")
    log(f"Platform          : {platform.platform()}")
    log(f"Αρχείο log        : {LOG_FILE}")
    log(f"Κύριο app αρχείο  : {app_file if app_file else 'Δεν βρέθηκε αυτόματα'}")
    log(f"Mode              : {'GUI only' if args.gui_only else 'Full application'}")
    log(f"Include runtime   : {include_runtime}")
    log(f"Torch variant     : {args.torch_variant}")
    if args.torch_index_url:
        log(f"Torch index-url   : {args.torch_index_url}")
    log("")
    log("Επιλεγμένες ομάδες πακέτων:")
    log(f"  GUI              : {', '.join(GUI_REQUIRED_PACKAGES)}")
    if full_install:
        log("  Torch            : torch")
        log(f"  Pipeline         : {', '.join(PIPELINE_REQUIRED_PACKAGES)}")
    if include_runtime:
        log(f"  Runtime deps     : {', '.join(RUNTIME_DEPENDENCY_PACKAGES)}")
    log("")

    if not args.no_upgrade_tools:
        code = upgrade_core_tools(dry_run=args.dry_run)
        if code != 0:
            log("⚠ Η αναβάθμιση εργαλείων απέτυχε. Συνεχίζω με την εγκατάσταση πακέτων.")

    log("\n--- Βασικά πακέτα GUI ---")
    code = install_package_group(
        GUI_REQUIRED_PACKAGES,
        "βασικών GUI πακέτων",
        upgrade=True,
        dry_run=args.dry_run,
    )
    if code != 0:
        log("✗ Η εγκατάσταση των βασικών GUI πακέτων απέτυχε.")
        return code

    if full_install:
        log("\n--- Torch ---")
        code = install_torch(
            torch_variant=args.torch_variant,
            torch_index_url=args.torch_index_url,
            upgrade=True,
            dry_run=args.dry_run,
        )
        if code != 0:
            log("✗ Η εγκατάσταση του torch απέτυχε.")
            return code

        log("\n--- Πακέτα training / inference pipeline ---")
        code = install_package_group(
            PIPELINE_REQUIRED_PACKAGES,
            "pipeline πακέτων",
            upgrade=True,
            dry_run=args.dry_run,
        )
        if code != 0:
            log("✗ Η εγκατάσταση των pipeline πακέτων απέτυχε.")
            return code

    if include_runtime:
        log("\n--- Έμμεσες εξαρτήσεις runtime ---")
        code = install_package_group(
            RUNTIME_DEPENDENCY_PACKAGES,
            "runtime εξαρτήσεων",
            upgrade=True,
            dry_run=args.dry_run,
        )
        if code != 0:
            log("✗ Η εγκατάσταση των runtime εξαρτήσεων απέτυχε.")
            return code

    if not args.skip_verify:
        code = verify_imports(verify_checks, dry_run=args.dry_run)
        if code != 0:
            log("✗ Το verify imports βρήκε προβλήματα. Δες το log για λεπτομέρειες.")
            return code
    else:
        log("ℹ Παραλείφθηκε το verify imports λόγω --skip-verify.")

    if not args.skip_compile_check:
        code = compile_check_app(app_file, dry_run=args.dry_run)
        if code != 0:
            log("✗ Ο py_compile έλεγχος του κύριου αρχείου απέτυχε.")
            return code
    else:
        log("ℹ Παραλείφθηκε ο py_compile έλεγχος λόγω --skip-compile-check.")

    log("\n✓ Ολοκληρώθηκε η διαδικασία εγκατάστασης.")
    log("")
    log("Προτεινόμενοι τρόποι χρήσης:")
    log("  Πλήρης εγκατάσταση (default):")
    log("      python install_packages_full_verified.py")
    log("  GUI μόνο:")
    log("      python install_packages_full_verified.py --gui-only")
    log("  Πλήρης εγκατάσταση με CUDA 12.1 torch:")
    log("      python install_packages_full_verified.py --torch-variant cu121")
    log("  Πλήρης εγκατάσταση με CUDA 12.4 torch:")
    log("      python install_packages_full_verified.py --torch-variant cu124")
    log("  Έλεγχος χωρίς install:")
    log("      python install_packages_full_verified.py --dry-run")
    log("")
    log("Σημείωση:")
    log("  Αν έχεις NVIDIA GPU, προτίμησε torch με κατάλληλο CUDA variant αντί για default install.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
