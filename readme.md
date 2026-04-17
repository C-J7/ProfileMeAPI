# ProfileMe API

A highly concurrent, asynchronous REST API that aggregates data from multiple public demographics APIs (Genderize, Agify, Nationalize) to generate and persist predictive user profiles based on a given name.


Built with **FastAPI**, **SQLAlchemy**, and **PostgreSQL** (NeonDB).


##  Live Demo
**Base URL:** `[link]`


##  Tech Stack
* **Framework:** FastAPI
* **Database:** PostgreSQL (Production) / SQLite (Local)
* **ORM:** SQLAlchemy
* **HTTP Client:** `httpx` (Asynchronous requests)
* **Data Types:** UUIDv7, UTC ISO 8601 Timestamps


##  Core Features
* **Concurrent API Aggregation:** Utilizes `asyncio.gather` to fetch data from three external APIs simultaneously, reducing latency.
* **Idempotent Profile Creation:** Safely handles duplicate name requests without creating redundant database entries or wasting external API calls.
* **Case-Insensitive Filtering:** Robust search functionality for retrieving profiles based on demographic parameters.
* **Strict Error Handling:** Graceful failure states for upstream API timeouts or missing data elements.


##  API Endpoints


### 1. Create a Profile
**POST** `/api/profiles`


```json
// Request
{
  "name": "ella"
}


// Response (201 Created)
{
  "status": "success",
  "data": {
    "id": "018e9f5b-1234-7abc-8def-123456789abc",
    "name": "ella",
    "gender": "female",
    "gender_probability": 0.99,
    "sample_size": 1234,
    "age": 46,
    "age_group": "adult",
    "country_id": "DRC",
    "country_probability": 0.85,
    "created_at": "2026-04-01T12:00:00Z"
  }
}
```


### 2. Get a Single Profile
**GET** `/api/profiles/{id}`
Returns a specific profile by its UUIDv7 identifier.


### 3. Get All Profiles
**GET** `/api/profiles`
Returns a list of all stored profiles.


**Optional Query Parameters (Case-Insensitive):**
* `?gender=male`
* `?country_id=NG`
* `?age_group=adult`


### 4. Delete a Profile
**DELETE** `/api/profiles/{id}`
Deletes the specified profile. Returns `204 No Content` on success.


---


##  Local Development Setup


**1. Clone the repository:**
```bash
git clone [https://github.com/yourusername/ProfileMeAPI.git](https://github.com/yourusername/ProfileMeAPI.git)
cd ProfileMeAPI
```


**2. Set up a virtual environment:**
```bash
python -m venv venv
source venv/Scripts/activate  # On Windows
# source venv/bin/activate    # On Mac/Linux
```


**3. Install dependencies:**
```bash
pip install -r requirements.txt
```


**4. Environment Variables:**
Create a `.env` file in the root directory. If `DATABASE_URL` is omitted, the application will default to a local SQLite database (`profiles.db`).
```env
DATABASE_URL="postgresql+psycopg://user:password@host/dbname?sslmode=require"
```


**5. Run the server:**
```bash
uvicorn main:app --reload
```
The API will be available at `http://127.0.0.1:8000`. You can view the interactive Swagger documentation at `http://127.0.0.1:8000/docs`.

