# Anand Transport Company — Complete Tracking System

## Included
- Customer website
- Docket/AWB tracking
- SQLite database
- Secure password hashing
- Admin login
- Add/edit/delete shipments
- Tracking status history
- JSON tracking API: `/api/track/<DOCKET>`

## Local setup

1. Install Python 3.10+.
2. Open terminal in this folder.
3. Run:
   `python -m venv venv`
4. Activate the environment.
   Windows:
   `venv\Scripts\activate`
5. Install:
   `pip install -r requirements.txt`
6. Run:
   `python app.py`
7. Open:
   `http://127.0.0.1:5000`

## Initial admin
Username: `admin`
Password: `admin123`

Change this before production.

## Production
Use a real domain and HTTPS, set a strong SECRET_KEY environment variable, change the admin password, use a production WSGI server, regular database backups, and preferably PostgreSQL/MySQL for a larger deployment.

The current version uses SQLite and is ideal for initial testing/small deployments.
