from datetime import datetime, timezone


def parse_fraction_to_float(value: str | None) -> float | None:
    if value is None:
        return None

    try:
        text = str(value).strip()
        if not text:
            return None
        if "/" not in text:
            return float(text)

        numerator, denominator = text.split("/", 1)
        numerator_float = float(numerator)
        denominator_float = float(denominator)
        if denominator_float == 0:
            return None
        return numerator_float / denominator_float
    except (TypeError, ValueError):
        return None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
