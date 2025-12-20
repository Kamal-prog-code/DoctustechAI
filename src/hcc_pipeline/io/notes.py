from pathlib import Path
import logging


logger = logging.getLogger(__name__)


def iter_note_files(notes_dir: Path) -> list[Path]:
    if not notes_dir.exists():
        raise FileNotFoundError(f"Notes directory not found: {notes_dir}")

    files = [path for path in notes_dir.iterdir() if path.is_file()]
    return sorted(files, key=lambda p: p.name)


def load_note_text(note_path: Path) -> str:
    try:
        return note_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        logger.warning("Falling back to latin-1 for %s", note_path)
        return note_path.read_text(encoding="latin-1")
