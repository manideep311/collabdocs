# CollabDocs

Backend API for a small document-collaboration app: users, workspaces with roles, documents with version history, threaded comments, tags and an audit log. Built with Django, Django REST Framework and PostgreSQL. Postman is the client.

## Setup

1. Create a PostgreSQL database, for example:
   ```
   createdb collabdocs
   ```
   Or, with Docker, start one in a container:
   ```
   docker run --name collabdocs-db -e POSTGRES_PASSWORD=yourpassword -e POSTGRES_DB=collabdocs -p 5433:5432 -d postgres:17
   ```
   Then use `DB_PORT=5433` and the same password in `.env`. Port 5433 avoids a clash with a local Postgres on 5432. Next time, just run `docker start collabdocs-db`.
2. Create and activate a virtual environment, then install the packages:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and fill in your own values (secret key and database login). The real `.env` is not committed.
4. Apply the migrations:
   ```
   python manage.py migrate
   ```
5. Start the server:
   ```
   python manage.py runserver
   ```
   The API is at `http://127.0.0.1:8000/api/`. Every request is printed in the console as `METHOD path status time`.

To run the tests: `python manage.py test` (the database user needs permission to create a test database).

## Endpoints

| Method | URL | What it does |
|---|---|---|
| POST | `/api/users/` | Create a user |
| GET | `/api/users/{id}/` | Get a user |
| POST | `/api/workspaces/` | Create a workspace and add the owner as admin |
| GET | `/api/workspaces/{id}/` | Get a workspace with its member count |
| POST | `/api/workspaces/{id}/members/` | Add a member with a role |
| GET | `/api/workspaces/{id}/members/` | List members with roles |
| GET | `/api/workspaces/{id}/summary/` | Document, member and comment counts |
| POST | `/api/documents/` | Create a document and its first version |
| PUT | `/api/documents/{id}/` | Update a document and save a new version |
| GET | `/api/documents/` | List documents, filter with `workspace`, `status`, `tag`, `search` |
| GET | `/api/documents/{id}/versions/` | All versions in order |
| GET | `/api/documents/{id}/stats/` | Version, comment and contributor counts |
| POST | `/api/documents/{id}/tags/` | Add tags, body `{"tags": ["python"]}` |
| POST | `/api/comments/` | Add a comment or a reply (`parent`) |
| GET | `/api/comments/?document={id}` | Threaded comments for a document |
| POST | `/api/tags/` | Create a tag |
| GET | `/api/audit-logs/` | Audit logs, filter with `actor`, `from`, `to` |

Errors come back with the right status code: 400 for bad input, 404 for a missing record, 409 for duplicates (same email, phone, tag or workspace member).

## Postman

1. Import `collabdocs.postman_collection.json` from the repository root.
2. Make sure the server is running. The `base_url` variable is `http://127.0.0.1:8000`.
3. Run the folders in order: Users, Workspaces, Documents, Comments, Tags, Audit Logs. Each request saves the ids the next ones need.

## Demo video

Link: https://drive.google.com/file/d/11qH76jDC4Dd4QwJMkEwxgc7LqvaRjMFd/view?usp=sharing
