# ProfileMe Backend for Insighta Labs+

The core backend system for Insighta Labs+, a secure profile intelligence platform featuring authentication, RBAC, and multi-interface consistency.

## System Architecture

The system consists of three distinct components communicating with this centralized FastAPI backend:

1. **Backend (This Repo):** Manages database operations, external API integration, JWT lifecycle, and role-based access control.
2. **CLI Application:** A globally installable command-line tool that authenticates via PKCE and interacts with the API using Bearer tokens.
3. **Web Portal:** A frontend dashboard that authenticates using secure, HTTP-only cookies to prevent XSS attacks.

## Authentication Flow

We utilize **GitHub OAuth with PKCE**:

1. Clients redirect users to GitHub to authorize.
2. On callback, the backend exchanges the code (and `code_verifier` for the CLI) for a GitHub token, fetches the user profile, and generates short-lived internal JWTs.
3. **Web Portal:** Tokens are set as HTTP-only, secure cookies.
4. **CLI:** Tokens are returned as JSON and stored locally in `~/.insighta/credentials.json`.

* Tokens adhere to strict expiry windows: Access Token (3 mins), Refresh Token (5 mins). Old refresh tokens are invalidated upon use.

## Role Enforcement Logic

* **Admin:** Full access. Can create profiles (`POST`), delete profiles (`DELETE`), and query data.
* **Analyst (Default):** Read-only access. Can search, filter, and export data, but cannot mutate records.
Roles are enforced at the router level using FastAPI `Depends()` middleware.

## Natural Language Parsing Approach

The system features a deterministic, rule-based natural language parser (no LLMs):

* Utilizes static dictionaries to map keywords (e.g., "males" -> "male", "teens" -> "teenager").
* Employs Regex rules to capture numeric ranges (e.g., "above 30" -> `min_age=30`).
* Matches country adjectives and names to ISO-3166-1 alpha-2 codes.
* Unrecognized or conflicting queries fail safely with a `400 Bad Request`.

## Local Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload

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

If the upstream demographic APIs fail or time out, the service now falls back to deterministic values instead of returning a 500 error.

### `GET /api/profiles/{profile_id}`

Returns a single profile by UUIDv7.

### `GET /api/profiles`

Supports combined filtering, sorting, and pagination.

Query parameters:

* `gender`
* `age_group`
* `country_id`
* `min_age`
* `max_age`
* `min_gender_probability`
* `min_country_probability`
* `sort_by=age|created_at|gender_probability`
* `order=asc|desc`
* `page` default `1`
* `limit` default `10`, capped at `50`

When a request asks for a higher limit, the API normalizes it down to `50` instead of rejecting the request.

### `GET /api/profiles/search?q=...`

Rule-based natural language search.

Supported examples:

* `young males from nigeria` -> `gender=male`, `min_age=16`, `max_age=24`, `country_id=NG`
* `females above 30` -> `gender=female`, `min_age=30`
* `adult males from kenya` -> `gender=male`, `age_group=adult`, `country_id=KE`
* `male and female teenagers above 17` -> `age_group=teenager`, `min_age=17`
* `nigerian women above 30` -> `gender=female`, `min_age=30`, `country_id=NG`

If the query cannot be interpreted, the API returns:

```json
{ "status": "error", "message": "Unable to interpret query" }
```

### `DELETE /api/profiles/{profile_id}`

Deletes a profile and returns `204 No Content`.

## Natural Language Parsing

The parser is deterministic and uses hashmaps plus regex rules, not LLMs.

Keyword groups:

* Gender synonyms map to `male` or `female`
* Age group synonyms map to `child`, `teenager`, `adult`, `senior`
* Country names map to ISO country codes
* `young` maps to ages `16-24`
* `above`, `over`, `at least` map to minimum age
* `below`, `under`, `at most` map to maximum age

Limitations:

* Only predefined keywords and age phrases are supported, but common filler words are ignored
* Spelling mistakes are not corrected
* Complex grammar, negation, and OR-based country queries are not supported
* If both male and female are present, gender is treated as non-restrictive

## Seeding

The app seeds from `profiles-2026.json` on startup when `SEED_FILE_PATH` is set or when the fallback file exists in the repo root.

Re-running the seed is safe because names are checked before insert.
