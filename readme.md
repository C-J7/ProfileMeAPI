# ProfileMe API

This is a FastAPI service for demographic profile storage, filtering, sorting, pagination, and with a rule-based natural language search.

## Overview
- Framework: FastAPI
- ORM: SQLAlchemy
- Database: PostgreSQL in production, SQLite locally, neonDb in prod.
- CORS: `Access-Control-Allow-Origin: *`

## Files
- `main.py` - API implementation
- `readme.md` - project documentation
- `requirements.txt` - dependencies
- `profiles-2026.json` - seed dataset

## Setup

```bash
python -m venv venv
source venv/Scripts/activate  #Windows
pip install -r requirements.txt #To install dependencies. 
```

Create a `.env` file if needed:

```env
DATABASE_URL="your-database-url"
SEED_FILE_PATH="profiles-2026.json"
```

Run locally:

```bash
uvicorn main:app --reload
```

## API Endpoints

### `POST /api/profiles`
Creates a profile from external demographic APIs. Returns an existing record if the name already exists.

### `GET /api/profiles/{profile_id}`
Returns a single profile by UUIDv7.

### `GET /api/profiles`
Supports combined filtering, sorting, and pagination.

Query parameters:

- `gender`
- `age_group`
- `country_id`
- `min_age`
- `max_age`
- `min_gender_probability`
- `min_country_probability`
- `sort_by=age|created_at|gender_probability`
- `order=asc|desc`
- `page` default `1`
- `limit` default `10`, max `50`

### `GET /api/profiles/search?q=...`
Rule-based natural language search.

Supported examples:

- `young males from nigeria` -> `gender=male`, `min_age=16`, `max_age=24`, `country_id=NG`
- `females above 30` -> `gender=female`, `min_age=30`
- `adult males from kenya` -> `gender=male`, `age_group=adult`, `country_id=KE`
- `male and female teenagers above 17` -> `age_group=teenager`, `min_age=17`

If the query cannot be interpreted, the API returns:

```json
{ "status": "error", "message": "Unable to interpret query" }
```

### `DELETE /api/profiles/{profile_id}`
Deletes a profile and returns `204 No Content`.

## Natural Language Parsing

The parser is deterministic and uses hashmaps plus regex rules, not LLMs.

Keyword groups:

- Gender synonyms map to `male` or `female`
- Age group synonyms map to `child`, `teenager`, `adult`, `senior`
- Country names map to ISO country codes
- `young` maps to ages `16-24`
- `above`, `over`, `at least` map to minimum age
- `below`, `under`, `at most` map to maximum age

Limitations:
- Only predefined keywords and age phrases are supported
- Spelling mistakes are not corrected
- Complex grammar, negation, and OR-based country queries are not supported
- If both male and female are present, gender is treated as non-restrictive

## Seeding
The app seeds from `profiles-2026.json` on startup when `SEED_FILE_PATH` is set or when the fallback file exists in the repo root.

Re-running the seed is safe because names are checked before insert.
