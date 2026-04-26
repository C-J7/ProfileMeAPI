import re
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import func

from constants import (
    AGE_GROUP_KEYWORDS,
    COUNTRY_ADJECTIVE_KEYWORDS,
    COUNTRY_KEYWORDS,
    GENDER_KEYWORDS,
    SORT_COLUMN_MAP,
    STOPWORDS,
    VALID_AGE_GROUPS,
    VALID_GENDERS,
    YOUNG_KEYWORDS,
)


def validate_query_filters(
    gender: Optional[str],
    age_group: Optional[str],
    country_id: Optional[str],
    min_age: Optional[int],
    max_age: Optional[int],
    min_gender_probability: Optional[float],
    min_country_probability: Optional[float],
    sort_by: str,
    order: str,
    page: int,
    limit: int,
) -> None:
    if gender is not None and gender.lower() not in VALID_GENDERS:
        raise HTTPException(status_code=422, detail="Invalid query parameters")
    if age_group is not None and age_group.lower() not in VALID_AGE_GROUPS:
        raise HTTPException(status_code=422, detail="Invalid query parameters")
    if country_id is not None and (len(country_id.strip()) != 2 or not country_id.strip().isalpha()):
        raise HTTPException(status_code=422, detail="Invalid query parameters")
    if min_age is not None and min_age < 0:
        raise HTTPException(status_code=422, detail="Invalid query parameters")
    if max_age is not None and max_age < 0:
        raise HTTPException(status_code=422, detail="Invalid query parameters")
    if min_age is not None and max_age is not None and min_age > max_age:
        raise HTTPException(status_code=422, detail="Invalid query parameters")
    if min_gender_probability is not None and not 0 <= min_gender_probability <= 1:
        raise HTTPException(status_code=422, detail="Invalid query parameters")
    if min_country_probability is not None and not 0 <= min_country_probability <= 1:
        raise HTTPException(status_code=422, detail="Invalid query parameters")
    if sort_by not in SORT_COLUMN_MAP:
        raise HTTPException(status_code=422, detail="Invalid query parameters")
    if order not in {"asc", "desc"}:
        raise HTTPException(status_code=422, detail="Invalid query parameters")
    if page < 1 or limit < 1:
        raise HTTPException(status_code=422, detail="Invalid query parameters")


def normalize_pagination(page: int, limit: int) -> tuple[int, int]:
    return max(page, 1), min(max(limit, 1), 50)


def normalize_natural_language_query(q: str) -> str:
    cleaned = re.sub(r"\s+", " ", re.sub(r"[^a-zA-Z0-9\s']", " ", q.lower())).strip()
    cleaned = re.sub(r"\b(?:and|or|of|the|a|an)\b", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def apply_profile_filters(
    query,
    *,
    gender: Optional[str] = None,
    age_group: Optional[str] = None,
    country_id: Optional[str] = None,
    min_age: Optional[int] = None,
    max_age: Optional[int] = None,
    min_gender_probability: Optional[float] = None,
    min_country_probability: Optional[float] = None,
):
    profile_model = query.column_descriptions[0]["entity"]

    if gender:
        query = query.filter(func.lower(profile_model.gender) == gender.strip().lower())
    if age_group:
        query = query.filter(func.lower(profile_model.age_group) == age_group.strip().lower())
    if country_id:
        query = query.filter(func.upper(profile_model.country_id) == country_id.strip().upper())
    if min_age is not None:
        query = query.filter(profile_model.age >= min_age)
    if max_age is not None:
        query = query.filter(profile_model.age <= max_age)
    if min_gender_probability is not None:
        query = query.filter(profile_model.gender_probability >= min_gender_probability)
    if min_country_probability is not None:
        query = query.filter(profile_model.country_probability >= min_country_probability)
    return query


def parse_natural_language_query(q: str) -> dict[str, Any]:
    cleaned = normalize_natural_language_query(q)
    if not cleaned:
        raise HTTPException(status_code=400, detail="Missing or empty parameter")

    filters: dict[str, Any] = {}
    parsed_any = False

    tokens = [token for token in cleaned.split() if token not in STOPWORDS]
    genders_found = {GENDER_KEYWORDS[token] for token in tokens if token in GENDER_KEYWORDS}
    if len(genders_found) == 1:
        filters["gender"] = next(iter(genders_found))
        parsed_any = True

    for token in tokens:
        if token in AGE_GROUP_KEYWORDS:
            filters["age_group"] = AGE_GROUP_KEYWORDS[token]
            parsed_any = True
            break

    if any(token in YOUNG_KEYWORDS for token in tokens):
        filters["min_age"] = 16
        filters["max_age"] = 24
        parsed_any = True

    above_match = re.search(r"(?:above|over|older than|greater than|at least)\s+(\d{1,3})", cleaned)
    if above_match:
        filters["min_age"] = int(above_match.group(1))
        parsed_any = True

    below_match = re.search(r"(?:below|under|younger than|less than|at most)\s+(\d{1,3})", cleaned)
    if below_match:
        filters["max_age"] = int(below_match.group(1))
        parsed_any = True

    country_id: Optional[str] = None
    country_match = re.search(r"\bfrom\s+([a-zA-Z\s']+)\b", cleaned)
    if country_match:
        country_phrase = country_match.group(1).strip()
        for keyword in sorted(COUNTRY_KEYWORDS.keys(), key=len, reverse=True):
            if country_phrase.startswith(keyword):
                country_id = COUNTRY_KEYWORDS[keyword]
                break
        if not country_id:
            for keyword in sorted(COUNTRY_ADJECTIVE_KEYWORDS.keys(), key=len, reverse=True):
                if country_phrase.startswith(keyword):
                    country_id = COUNTRY_ADJECTIVE_KEYWORDS[keyword]
                    break

    if not country_id:
        for keyword in sorted(COUNTRY_KEYWORDS.keys(), key=len, reverse=True):
            if re.search(rf"\b{re.escape(keyword)}\b", cleaned):
                country_id = COUNTRY_KEYWORDS[keyword]
                break

    if not country_id:
        for keyword in sorted(COUNTRY_ADJECTIVE_KEYWORDS.keys(), key=len, reverse=True):
            if re.search(rf"\b{re.escape(keyword)}\b", cleaned):
                country_id = COUNTRY_ADJECTIVE_KEYWORDS[keyword]
                break

    if country_id:
        filters["country_id"] = country_id
        parsed_any = True

    if filters.get("min_age") is not None and filters.get("max_age") is not None and filters["min_age"] > filters["max_age"]:
        raise HTTPException(status_code=422, detail="Invalid query parameters")

    if not parsed_any:
        raise HTTPException(status_code=400, detail="Unable to interpret query")

    return filters