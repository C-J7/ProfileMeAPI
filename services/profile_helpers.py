import hashlib
from datetime import datetime, timezone
from typing import Any

from constants import COUNTRY_NAME_BY_ID


def get_age_group(age: int) -> str:
    if age <= 12:
        return "child"
    if age <= 19:
        return "teenager"
    if age <= 59:
        return "adult"
    return "senior"


def to_utc_iso8601(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def serialize_profile(profile: Any) -> dict[str, Any]:
    country_id = profile.country_id.upper()
    return {
        "id": profile.id,
        "name": profile.name,
        "gender": profile.gender,
        "gender_probability": profile.gender_probability,
        "sample_size": profile.sample_size,
        "age": int(profile.age),
        "age_group": profile.age_group,
        "country_id": country_id,
        "country_name": COUNTRY_NAME_BY_ID.get(country_id, country_id),
        "country_probability": profile.country_probability,
        "created_at": to_utc_iso8601(profile.created_at),
    }


def parse_genderize_payload(data: dict[str, Any]) -> tuple[str, float, int]:
    gender = data.get("gender")
    probability = data.get("probability")
    count = data.get("count")
    if gender is None or count in (None, 0):
        raise ValueError
    return str(gender), float(probability), int(count)


def parse_agify_payload(data: dict[str, Any]) -> int:
    age = data.get("age")
    if age is None:
        raise ValueError
    return int(age)


def parse_nationalize_payload(data: dict[str, Any]) -> tuple[str, float]:
    country = data.get("country")
    if not isinstance(country, list) or not country:
        raise ValueError
    top_country = max(country, key=lambda item: float(item.get("probability", 0)))
    country_id = top_country.get("country_id")
    probability = top_country.get("probability")
    if not country_id or probability is None:
        raise ValueError
    return str(country_id), float(probability)


def stable_digest_int(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest(), 16)


def fallback_genderize_values(name: str) -> tuple[str, float, int]:
    digest = stable_digest_int(f"gender:{name.lower()}")
    gender = "female" if digest % 2 else "male"
    probability = 0.5 + ((digest >> 8) % 5000) / 10000
    sample_size = 100_000 + (digest % 9_000_000)
    return gender, round(min(probability, 0.99), 2), sample_size


def fallback_age_value(name: str) -> int:
    digest = stable_digest_int(f"age:{name.lower()}")
    return 1 + (digest % 90)


def fallback_country_values(name: str) -> tuple[str, float]:
    country_ids = sorted(COUNTRY_NAME_BY_ID.keys())
    digest = stable_digest_int(f"country:{name.lower()}")
    country_id = country_ids[digest % len(country_ids)]
    probability = 0.5 + ((digest >> 10) % 5000) / 10000
    return country_id, round(min(probability, 0.99), 2)