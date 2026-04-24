import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from sqlalchemy import Column, DateTime, Float, Integer, String, create_engine, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from uuid6 import uuid7


load_dotenv()




def normalize_database_url(url: str) -> str:

    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://") and "+" not in url.split("://", 1)[0]:
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url




# Local default is SQLite. In production, neondb.
DATABASE_URL = normalize_database_url(os.getenv("DATABASE_URL", "sqlite:///./profiles.db"))


engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


VALID_GENDERS = {"male", "female"}
VALID_AGE_GROUPS = {"child", "teenager", "adult", "senior"}

SORT_COLUMN_MAP = {
    "age": "age",
    "created_at": "created_at",
    "gender_probability": "gender_probability",
}

COUNTRY_KEYWORDS = {
    "nigeria": "NG",
    "kenya": "KE",
    "angola": "AO",
    "benin": "BJ",
    "ghana": "GH",
    "uganda": "UG",
    "tanzania": "TZ",
    "south africa": "ZA",
    "zambia": "ZM",
    "zimbabwe": "ZW",
    "ethiopia": "ET",
    "cameroon": "CM",
    "senegal": "SN",
    "ivory coast": "CI",
    "cote d'ivoire": "CI",
    "cote divoire": "CI",
    "rwanda": "RW",
    "burundi": "BI",
    "algeria": "DZ",
    "morocco": "MA",
    "egypt": "EG",
    "tunisia": "TN",
    "namibia": "NA",
    "botswana": "BW",
    "sierra leone": "SL",
    "liberia": "LR",
    "mali": "ML",
    "burkina faso": "BF",
    "chad": "TD",
    "niger": "NE",
    "congo": "CG",
    "dr congo": "CD",
    "democratic republic of congo": "CD",
    "united states": "US",
    "usa": "US",
    "canada": "CA",
    "united kingdom": "GB",
    "uk": "GB",
    "france": "FR",
    "germany": "DE",
    "italy": "IT",
    "spain": "ES",
    "portugal": "PT",
    "india": "IN",
    "china": "CN",
    "japan": "JP",
    "brazil": "BR",
    "mexico": "MX",
    "argentina": "AR",
}

COUNTRY_NAME_BY_ID = {
    "NG": "Nigeria",
    "KE": "Kenya",
    "AO": "Angola",
    "BJ": "Benin",
    "GH": "Ghana",
    "UG": "Uganda",
    "TZ": "Tanzania",
    "ZA": "South Africa",
    "ZM": "Zambia",
    "ZW": "Zimbabwe",
    "ET": "Ethiopia",
    "CM": "Cameroon",
    "SN": "Senegal",
    "CI": "Cote d'Ivoire",
    "RW": "Rwanda",
    "BI": "Burundi",
    "DZ": "Algeria",
    "MA": "Morocco",
    "EG": "Egypt",
    "TN": "Tunisia",
    "NA": "Namibia",
    "BW": "Botswana",
    "SL": "Sierra Leone",
    "LR": "Liberia",
    "ML": "Mali",
    "BF": "Burkina Faso",
    "TD": "Chad",
    "NE": "Niger",
    "CG": "Congo",
    "CD": "Democratic Republic of the Congo",
    "US": "United States",
    "CA": "Canada",
    "GB": "United Kingdom",
    "FR": "France",
    "DE": "Germany",
    "IT": "Italy",
    "ES": "Spain",
    "PT": "Portugal",
    "IN": "India",
    "CN": "China",
    "JP": "Japan",
    "BR": "Brazil",
    "MX": "Mexico",
    "AR": "Argentina",
}

GENDER_KEYWORDS = {
    "male": "male",
    "males": "male",
    "man": "male",
    "men": "male",
    "boy": "male",
    "boys": "male",


    "female": "female",
    "females": "female",
    "woman": "female",
    "women": "female",
    "girl": "female",
    "girls": "female",


}

AGE_GROUP_KEYWORDS = {
    "child": "child",
    "children": "child",
    "baby": "child",
    "infant": "child",
    "toddler": "child",
    "kid": "child",
    "kids": "child",
    "teen": "teenager",
    "teens": "teenager",
    "teenager": "teenager",
    "teenagers": "teenager",
    "adult": "adult",
    "adults": "adult",
    "senior": "senior",
    "seniors": "senior",
    "elderly": "senior",
    "old": "senior",
    "elders": "senior",
    "old-timer": "senior",
}

YOUNG_KEYWORDS = {"young", "youth", "youths", "juvenile", "juveniles", "adolescent", "adolescents"}


class Profile(Base):
    __tablename__ = "profiles"


    id = Column(String, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    gender = Column(String, nullable=False)
    gender_probability = Column(Float, nullable=False)
    age = Column(Integer, nullable=False)
    age_group = Column(String, nullable=False)
    country_id = Column(String, nullable=False)
    country_name = Column(String, nullable=False)
    country_probability = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))



Base.metadata.create_all(bind=engine)



def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()



app = FastAPI(title="ProfileMeAPI")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)



def error_response(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"status": "error", "message": message})



@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    query_errors = [err for err in exc.errors() if err.get("loc") and err["loc"][0] == "query"]
    if query_errors:
        return error_response(422, "Invalid query parameters")
    return error_response(422, "Invalid type")



@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, str) else "Server error"
    return error_response(exc.status_code, detail)



@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return error_response(500, "Server error")



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



def serialize_profile(profile: Profile) -> dict[str, Any]:
    return {
        "id": profile.id,
        "name": profile.name,
        "gender": profile.gender,
        "gender_probability": profile.gender_probability,
        "age": int(profile.age),
        "age_group": profile.age_group,
        "country_id": profile.country_id,
        "country_name": profile.country_name,
        "country_probability": profile.country_probability,
        "created_at": to_utc_iso8601(profile.created_at),
    }



def parse_genderize_payload(data: dict[str, Any]) -> tuple[str, float]:
    gender = data.get("gender")
    probability = data.get("probability")
    count = data.get("count")
    if gender is None or count in (None, 0):
        raise ValueError
    return str(gender), float(probability)




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
    if page < 1 or not 1 <= limit <= 50:
        raise HTTPException(status_code=422, detail="Invalid query parameters")


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
    if gender:
        query = query.filter(func.lower(Profile.gender) == gender.strip().lower())
    if age_group:
        query = query.filter(func.lower(Profile.age_group) == age_group.strip().lower())
    if country_id:
        query = query.filter(func.upper(Profile.country_id) == country_id.strip().upper())
    if min_age is not None:
        query = query.filter(Profile.age >= min_age)
    if max_age is not None:
        query = query.filter(Profile.age <= max_age)
    if min_gender_probability is not None:
        query = query.filter(Profile.gender_probability >= min_gender_probability)
    if min_country_probability is not None:
        query = query.filter(Profile.country_probability >= min_country_probability)
    return query


def parse_natural_language_query(q: str) -> dict[str, Any]:
    cleaned = re.sub(r"\s+", " ", re.sub(r"[^a-zA-Z0-9\s']", " ", q.lower())).strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Missing or empty parameter")

    filters: dict[str, Any] = {}
    parsed_any = False

    tokens = cleaned.split()
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
        for keyword in sorted(COUNTRY_KEYWORDS.keys(), key=len, reverse=True):
            if re.search(rf"\b{re.escape(keyword)}\b", cleaned):
                country_id = COUNTRY_KEYWORDS[keyword]
                break

    if country_id:
        filters["country_id"] = country_id
        parsed_any = True

    if filters.get("min_age") is not None and filters.get("max_age") is not None and filters["min_age"] > filters["max_age"]:
        raise HTTPException(status_code=422, detail="Invalid query parameters")

    if not parsed_any:
        raise HTTPException(status_code=400, detail="Unable to interpret query")

    return filters


def maybe_seed_profiles(db: Session) -> None:
    seed_path = os.getenv("SEED_FILE_PATH", "profiles-2026.json")
    if not seed_path:
        return

    path = Path(seed_path)
    if not path.exists():
        return

    try:
        with path.open("r", encoding="utf-8") as fp:
            payload = json.load(fp)
    except Exception:
        return

    if not isinstance(payload, list):
        return

    for item in payload:
        if not isinstance(item, dict):
            continue

        name = str(item.get("name", "")).strip()
        if not name:
            continue

        exists = db.query(Profile).filter(func.lower(Profile.name) == name.lower()).first()
        if exists:
            continue

        raw_country_id = str(item.get("country_id", "")).strip().upper()
        if len(raw_country_id) != 2 or not raw_country_id.isalpha():
            continue

        country_name = str(item.get("country_name", "")).strip() or COUNTRY_NAME_BY_ID.get(raw_country_id, raw_country_id)

        created_at_raw = item.get("created_at")
        created_at = datetime.now(timezone.utc)
        if isinstance(created_at_raw, str) and created_at_raw:
            try:
                created_at = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00")).astimezone(timezone.utc)
            except Exception:
                created_at = datetime.now(timezone.utc)

        try:
            profile = Profile(
                id=str(item.get("id") or uuid7()),
                name=name,
                gender=str(item.get("gender", "")).strip().lower(),
                gender_probability=float(item.get("gender_probability", 0)),
                age=int(item.get("age", 0)),
                age_group=str(item.get("age_group", "")).strip().lower(),
                country_id=raw_country_id,
                country_name=country_name,
                country_probability=float(item.get("country_probability", 0)),
                created_at=created_at,
            )
        except Exception:
            continue

        db.add(profile)

    try:
        db.commit()
    except Exception:
        db.rollback()



async def fetch_external_json(client: httpx.AsyncClient, url: str, service_name: str) -> dict[str, Any]:
    try:
        response = await client.get(url, timeout=10.0)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError
        return data
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"{service_name} returned an invalid response") from exc



@app.post("/api/profiles", status_code=status.HTTP_201_CREATED)
async def create_profile(request: Request, db: Session = Depends(get_db)):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Missing or empty name")


    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Invalid type")


    if "name" not in payload:
        raise HTTPException(status_code=400, detail="Missing or empty name")


    name = payload.get("name")
    if not isinstance(name, str):
        raise HTTPException(status_code=422, detail="Invalid type")


    normalized_name = name.strip()
    if not normalized_name:
        raise HTTPException(status_code=400, detail="Missing or empty name")


    existing_profile = db.query(Profile).filter(func.lower(Profile.name) == normalized_name.lower()).first()
    if existing_profile:
        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "message": "Profile already exists",
                "data": serialize_profile(existing_profile),
            },
        )


    async with httpx.AsyncClient() as client:
        genderize_task = fetch_external_json(client, f"https://api.genderize.io?name={normalized_name}", "Genderize")
        agify_task = fetch_external_json(client, f"https://api.agify.io?name={normalized_name}", "Agify")
        nationalize_task = fetch_external_json(client, f"https://api.nationalize.io?name={normalized_name}", "Nationalize")


        genderize_data, agify_data, nationalize_data = await asyncio.gather(
            genderize_task,
            agify_task,
            nationalize_task,
        )


    try:
        gender, gender_probability = parse_genderize_payload(genderize_data)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Genderize returned an invalid response") from exc


    try:
        age = parse_agify_payload(agify_data)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Agify returned an invalid response") from exc


    try:
        country_id, country_probability = parse_nationalize_payload(nationalize_data)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Nationalize returned an invalid response") from exc


    new_profile = Profile(
        id=str(uuid7()),
        name=normalized_name,
        gender=gender.lower(),
        gender_probability=gender_probability,
        age=age,
        age_group=get_age_group(age),
        country_id=country_id.upper(),
        country_name=COUNTRY_NAME_BY_ID.get(country_id.upper(), country_id.upper()),
        country_probability=country_probability,
        created_at=datetime.now(timezone.utc),
    )


    db.add(new_profile)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Handles race conditions: returns already-created row to preserve idempotency.
        existing_profile = db.query(Profile).filter(func.lower(Profile.name) == normalized_name.lower()).first()
        if existing_profile:
            return JSONResponse(
                status_code=200,
                content={
                    "status": "success",
                    "message": "Profile already exists",
                    "data": serialize_profile(existing_profile),
                },
            )
        raise HTTPException(status_code=500, detail="Server error")


    db.refresh(new_profile)
    return JSONResponse(status_code=201, content={"status": "success", "data": serialize_profile(new_profile)})




@app.get("/api/profiles/{profile_id}")
async def get_single_profile(profile_id: str, db: Session = Depends(get_db)):
    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"status": "success", "data": serialize_profile(profile)}




@app.get("/api/profiles")
async def get_all_profiles(
    gender: Optional[str] = Query(default=None),
    age_group: Optional[str] = Query(default=None),
    country_id: Optional[str] = Query(default=None),
    min_age: Optional[int] = Query(default=None),
    max_age: Optional[int] = Query(default=None),
    min_gender_probability: Optional[float] = Query(default=None),
    min_country_probability: Optional[float] = Query(default=None),
    sort_by: str = Query(default="created_at"),
    order: str = Query(default="desc"),
    page: int = Query(default=1),
    limit: int = Query(default=10),
    db: Session = Depends(get_db),
):
    validate_query_filters(
        gender,
        age_group,
        country_id,
        min_age,
        max_age,
        min_gender_probability,
        min_country_probability,
        sort_by,
        order,
        page,
        limit,
    )

    query = db.query(Profile)
    query = apply_profile_filters(
        query,
        gender=gender,
        age_group=age_group,
        country_id=country_id,
        min_age=min_age,
        max_age=max_age,
        min_gender_probability=min_gender_probability,
        min_country_probability=min_country_probability,
    )

    total = query.count()

    sort_column = getattr(Profile, SORT_COLUMN_MAP[sort_by])
    if order == "asc":
        query = query.order_by(sort_column.asc())
    else:
        query = query.order_by(sort_column.desc())

    offset = (page - 1) * limit
    profiles = query.offset(offset).limit(limit).all()

    return {
        "status": "success",
        "page": page,
        "limit": limit,
        "total": total,
        "data": [serialize_profile(profile) for profile in profiles],
    }


@app.get("/api/profiles/search")
async def search_profiles(
    q: Optional[str] = Query(default=None),
    page: int = Query(default=1),
    limit: int = Query(default=10),
    db: Session = Depends(get_db),
):
    if q is None or not isinstance(q, str) or not q.strip():
        raise HTTPException(status_code=400, detail="Missing or empty parameter")

    if page < 1 or not 1 <= limit <= 50:
        raise HTTPException(status_code=422, detail="Invalid query parameters")

    parsed_filters = parse_natural_language_query(q)

    query = db.query(Profile)
    query = apply_profile_filters(
        query,
        gender=parsed_filters.get("gender"),
        age_group=parsed_filters.get("age_group"),
        country_id=parsed_filters.get("country_id"),
        min_age=parsed_filters.get("min_age"),
        max_age=parsed_filters.get("max_age"),
    )

    total = query.count()
    offset = (page - 1) * limit
    profiles = query.order_by(Profile.created_at.desc()).offset(offset).limit(limit).all()

    return {
        "status": "success",
        "page": page,
        "limit": limit,
        "total": total,
        "data": [serialize_profile(profile) for profile in profiles],
    }


@app.on_event("startup")
def seed_on_startup() -> None:
    db = SessionLocal()
    try:
        maybe_seed_profiles(db)
    finally:
        db.close()


@app.delete("/api/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile(profile_id: str, db: Session = Depends(get_db)):
    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    db.delete(profile)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

