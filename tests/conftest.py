from pathlib import Path

import pytest

BOOKS = Path(__file__).resolve().parents[1] / "test_books"


def _book(prefix: str) -> Path:
    hits = sorted(BOOKS.glob(f"{prefix}*"))
    if not hits:
        pytest.skip(f"test book {prefix}* not found in {BOOKS}")
    return hits[0]


@pytest.fixture
def books_dir() -> Path:
    if not BOOKS.exists():
        pytest.skip("test_books/ not found")
    return BOOKS


@pytest.fixture
def gir_path() -> Path:
    return _book("Гиршович")


@pytest.fixture
def vor_path() -> Path:
    return _book("Воронин")


@pytest.fixture
def saf_path() -> Path:
    return _book("Сафронов")


@pytest.fixture
def asm_path() -> Path:
    return _book("Asm Metals Handbook")
