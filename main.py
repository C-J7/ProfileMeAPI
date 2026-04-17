import asyncio
import os
from datetime import datetime, timezone
from typing import Any, Optional


import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
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
    # Some hosts expose postgres://; SQLAlchemy expects a fully qualified driver URL.
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://") and "+" not in url.split("://", 1)[0]:
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url




# Local default is SQLite. In production, set DATABASE_URL.
DATABASE_URL = normalize_database_url(os.getenv("DATABASE_URL", "sqlite:///./profiles.db"))


engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
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
        "sample_size": profile.sample_size,
        "age": profile.age,
        "age_group": profile.age_group,
        "country_id": profile.country_id,
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
        gender, gender_probability, sample_size = parse_genderize_payload(genderize_data)
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
        gender=gender,
        gender_probability=gender_probability,
        sample_size=sample_size,
        age=age,
        age_group=get_age_group(age),
        country_id=country_id,
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
    gender: Optional[str] = None,
    country_id: Optional[str] = None,
    age_group: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(Profile)


    if gender:
        query = query.filter(func.lower(Profile.gender) == gender.strip().lower())
    if country_id:
        query = query.filter(func.lower(Profile.country_id) == country_id.strip().lower())
    if age_group:
        query = query.filter(func.lower(Profile.age_group) == age_group.strip().lower())


    profiles = query.all()
    data = [
        {
            "id": profile.id,
            "name": profile.name,
            "gender": profile.gender,
            "age": profile.age,
            "age_group": profile.age_group,
            "country_id": profile.country_id,
        }
        for profile in profiles
    ]


    return {"status": "success", "count": len(data), "data": data}




@app.delete("/api/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile(profile_id: str, db: Session = Depends(get_db)):
    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    db.delete(profile)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

