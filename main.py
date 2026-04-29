import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


import httpx
import enum
import time
from collections import defaultdict
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from dotenv import load_dotenv
from sqlalchemy import Column, Boolean, DateTime, Float, Integer, String, create_engine, func, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from uuid6 import uuid7

import csv
from io import StringIO


from constants import (
    SORT_COLUMN_MAP, COUNTRY_NAME_BY_ID
)

from services.profile_helpers import (
    fallback_age_value,
    fallback_country_values,
    fallback_genderize_values,
    get_age_group,
    parse_agify_payload,
    parse_genderize_payload,
    parse_nationalize_payload,
    serialize_profile,
)
from services.query_helpers import (
    apply_profile_filters,
    normalize_pagination,
    parse_natural_language_query,
    validate_query_filters,
)


load_dotenv()




def normalize_database_url(url: str) -> str:

    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://") and "+" not in url.split("://", 1)[0]:
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url




def get_default_database_url() -> str:
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return normalize_database_url(database_url)

    if os.getenv("VERCEL") == "1":
        return "sqlite:////tmp/profiles.db"

    return "sqlite:///./profiles.db"




# Local default is SQLite. In production, neondb.
def build_database_engine() -> tuple[Any, str]:
    candidate_urls = [get_default_database_url()]
    fallback_sqlite_url = "sqlite:////tmp/profiles.db" if os.getenv("VERCEL") == "1" else "sqlite:///./profiles.db"
    if fallback_sqlite_url not in candidate_urls:
        candidate_urls.append(fallback_sqlite_url)

    last_error: Exception | None = None
    for database_url in candidate_urls:
        try:
            candidate_engine = create_engine(
                database_url,
                connect_args={"check_same_thread": False} if database_url.startswith("sqlite") else {},
            )
            with candidate_engine.connect() as connection:
                connection.exec_driver_sql("SELECT 1")
            return candidate_engine, database_url
        except Exception as exc:
            last_error = exc

    raise RuntimeError("Unable to initialize database") from last_error


engine, DATABASE_URL = build_database_engine()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Profile(Base):
    __tablename__ = "profiles"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    gender = Column(String, nullable=False)
    gender_probability = Column(Float, nullable=False)
    sample_size = Column(Integer, nullable=False)
    age = Column(Integer, nullable=False)
    age_group = Column(String, nullable=False)
    country_id = Column(String, nullable=False)
    country_probability = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

class StatusEnum(enum.Enum): 
    admin = "admin"
    analyst = "analyst" 

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True)
    github_id = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, nullable=False)
    email = Column(String, nullable=True)
    avatar_url = Column(String, nullable=True)
    role = Column(String, nullable=False, default="analyst")
    is_active = Column(Boolean, nullable=False, default=True)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    refresh_token = Column(String, nullable=True)

Base.metadata.create_all(bind=engine)


def ensure_profiles_schema() -> None:
    inspector = inspect(engine)
    existing_columns = {column["name"] for column in inspector.get_columns("profiles")}
    missing_columns = [column for column in Profile.__table__.columns if column.name not in existing_columns]
    if not missing_columns:
        return

    with engine.begin() as connection:
        for column in missing_columns:
            if column.name == "country_name":
                connection.exec_driver_sql(
                    "ALTER TABLE profiles ADD COLUMN country_name VARCHAR NOT NULL DEFAULT ''"
                )




def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()



app = FastAPI(title="ProfileMeAPI")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "https://insighta-web-khaki-two.vercel.app/"], 
    allow_credentials=True,                  
    allow_methods=["*"],
    allow_headers=["*"],
)

import time
from collections import defaultdict
from fastapi.responses import JSONResponse

# In-memory rate limiting
RATE_LIMITS = {
    "auth": {"limit": 10, "window": 60},
    "api": {"limit": 60, "window": 60}
}
request_logs = defaultdict(list)

@app.middleware("http")
async def strict_platform_middleware(request: Request, call_next):
    start_time = time.time()
    path = request.url.path
    client_ip = request.client.host if request.client else "unknown"

    #  API Versioning Check
    if path.startswith("/api/"):
        if request.headers.get("X-API-Version") != "1":
            return JSONResponse(
                status_code=400, 
                content={"status": "error", "message": "API version header required"}
            )

    # Rate Limiting Check
    current_time = time.time()
    limit_type = "auth" if path.startswith("/auth/") else "api"
    window = RATE_LIMITS[limit_type]["window"]
    max_requests = RATE_LIMITS[limit_type]["limit"]

    # Clean old requests
    request_logs[client_ip] = [t for t in request_logs[client_ip] if current_time - t < window]
    
    if len(request_logs[client_ip]) >= max_requests:
        return JSONResponse(status_code=429, content={"status": "error", "message": "Too Many Requests"})
    
    request_logs[client_ip].append(current_time)

    # Process Request
    response = await call_next(request)

    # Logging
    process_time = time.time() - start_time
    print(f"[{request.method}] {path} - {response.status_code} - {process_time:.4f}s")

    return response



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



def seed_profiles(db: Session) -> None:
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

    existing_names = {
        name.lower()
        for (name,) in db.query(Profile.name).all()
        if isinstance(name, str) and name.strip()
    }
    profiles_to_insert = []

    for item in payload:
        if not isinstance(item, dict):
            continue

        name = str(item.get("name", "")).strip()
        if not name:
            continue

        if name.lower() in existing_names:
            continue

        raw_country_id = str(item.get("country_id", "")).strip().upper()
        if len(raw_country_id) != 2 or not raw_country_id.isalpha():
            continue

        try:
            profiles_to_insert.append(
                Profile(
                id=str(item.get("id") or uuid7()),
                name=name,
                gender=str(item.get("gender", "")).strip().lower(),
                gender_probability=float(item.get("gender_probability", 0)),
                sample_size=int(item.get("sample_size", 0)),
                age=int(item.get("age", 0)),
                age_group=str(item.get("age_group", "")).strip().lower(),
                country_id=raw_country_id,
                country_probability=float(item.get("country_probability", 0)),
                    created_at=datetime.fromisoformat(str(item.get("created_at", "")).replace("Z", "+00:00")).astimezone(timezone.utc)
                    if isinstance(item.get("created_at"), str) and item.get("created_at")
                    else datetime.now(timezone.utc),
                )
            )
        except Exception:
            continue

        existing_names.add(name.lower())

    if profiles_to_insert:
        db.add_all(profiles_to_insert)

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


from auth import require_admin, get_current_user, router as auth_router

@app.post("/api/profiles", status_code=status.HTTP_201_CREATED)
async def create_profile(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
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
            return_exceptions=True,
        )


    try:
        gender, gender_probability, sample_size = parse_genderize_payload(genderize_data)
    except Exception as exc:
        gender, gender_probability, sample_size = fallback_genderize_values(normalized_name)


    try:
        age = parse_agify_payload(agify_data)
    except Exception as exc:
        age = fallback_age_value(normalized_name)


    try:
        country_id, country_probability = parse_nationalize_payload(nationalize_data)
    except Exception as exc:
        country_id, country_probability = fallback_country_values(normalized_name)


    new_profile = Profile(
        id=str(uuid7()),
        name=normalized_name,
        gender=gender.lower(),
        gender_probability=gender_probability,
        sample_size=sample_size,
        age=age,
        age_group=get_age_group(age),
        country_id=country_id.upper(),
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




@app.get("/api/profiles/search")
async def search_profiles(
    q: Optional[str] = Query(default=None),
    page: int = Query(default=1),
    limit: int = Query(default=10),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if q is None or not isinstance(q, str) or not q.strip():
        raise HTTPException(status_code=400, detail="Missing or empty parameter")

    page, limit = normalize_pagination(page, limit)

    try:
        parsed_filters = parse_natural_language_query(q)
    except HTTPException as exc:
        if exc.status_code == 400 and exc.detail == "Unable to interpret query":
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "Unable to interpret query"},
            )
        raise

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


@app.get("/api/profiles/{profile_id}")
async def get_single_profile(profile_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
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
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    page, limit = normalize_pagination(page, limit)
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
    total_pages = (total + limit - 1) // limit if limit > 0 else 1

    return {
        "status": "success",
        "page": page,
        "limit": limit,
        "total": total,
        "total_pages": total_pages,
        "links": {
            "self": f"/api/profiles?page={page}&limit={limit}",
            "next": f"/api/profiles?page={page+1}&limit={limit}" if page < total_pages else None,
            "prev": f"/api/profiles?page={page-1}&limit={limit}" if page > 1 else None
        },
        "data": [serialize_profile(profile) for profile in profiles],

    }


@app.get("/api/profiles/export")
async def export_profiles(
    gender: Optional[str] = Query(default=None),
    age_group: Optional[str] = Query(default=None),
    country_id: Optional[str] = Query(default=None),
    min_age: Optional[int] = Query(default=None),
    max_age: Optional[int] = Query(default=None),
    min_gender_probability: Optional[float] = Query(default=None),
    min_country_probability: Optional[float] = Query(default=None),
    sort_by: str = Query(default="created_at"),
    order: str = Query(default="desc"),
   
    format: str = Query(default="csv"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if format.lower() != "csv":
        raise HTTPException(status_code=400, detail="Only CSV format is supported")

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


    if sort_by in SORT_COLUMN_MAP:
        sort_column = getattr(Profile, SORT_COLUMN_MAP[sort_by])
        if order.lower() == "asc":
            query = query.order_by(sort_column.asc())
        else:
            query = query.order_by(sort_column.desc())

    profiles = query.all()

    stream = StringIO()
    writer = csv.writer(stream)
    
    writer.writerow(["id", "name", "gender", "gender_probability", "age", "age_group", "country_id", "country_name", "country_probability", "created_at"])
    
    for p in profiles:
        writer.writerow([
            p.id, p.name, p.gender, p.gender_probability, p.age, p.age_group, 
            p.country_id, COUNTRY_NAME_BY_ID.get(p.country_id, p.country_id), 
            p.country_probability, p.created_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        ])

    response = StreamingResponse(iter([stream.getvalue()]), media_type="text/csv")
    response.headers["Content-Disposition"] = f'attachment; filename="profiles_{int(time.time())}.csv"'
    return response


@app.on_event("startup")
def seed_on_startup() -> None:
    ensure_profiles_schema()
    db = SessionLocal()
    try:
        seed_profiles(db)
    finally:
        db.close()


@app.delete("/api/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile(profile_id: str, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    db.delete(profile)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

app.include_router(auth_router)