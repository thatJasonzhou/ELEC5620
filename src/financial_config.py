"""Deposit policy; process environment overrides the project-local .env file."""
import os
from pathlib import Path
from decimal import Decimal, InvalidOperation


def deposit_rate():
    name = "ELEC5620_DEPOSIT_RATE"
    raw = os.environ.get(name)
    if raw is None:
        path = Path(__file__).resolve().parents[1] / ".env"
        if path.is_file():
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                key, separator, value = line.strip().partition("=")
                if separator and key.strip() == name:
                    raw = value.split("#", 1)[0].strip().strip("\"'")
    if raw is None:
        raise ValueError(f"{name} is required (environment or project .env)")
    try:
        rate = Decimal(raw)
        if not rate.is_finite() or not 0 < rate <= 1:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        raise ValueError(f"{name} must be a finite decimal with 0 < rate <= 1") from None
    return rate
