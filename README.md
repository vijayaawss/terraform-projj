# WanderShare Flask setup

## Local setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
flask db init
flask db migrate -m "Create places and place images"
flask db upgrade
flask run
```

Open `http://127.0.0.1:5000/`.

For local development, `AUTO_CREATE_DB=1` creates missing SQL tables automatically. Restart Flask after changing `.env`. For production, set `AUTO_CREATE_DB=0` and run `flask db upgrade` during deployment.

## AWS RDS MySQL

Set these values in `.env`:

```env
DATABASE_URL=
DB_HOST=your-instance.xxxxxxxxxxxx.ap-south-1.rds.amazonaws.com
DB_PORT=3306
DB_NAME=wandershare
DB_USER=admin
DB_PASSWORD=your_password
DB_SSL_CA=C:/full/path/to/global-bundle.pem
AUTO_CREATE_DB=1
```

`DB_HOST` must contain only the RDS endpoint, not `https://`. The app constructs a safely encoded `mysql+pymysql` connection URL, so special characters in the password are supported. Test it at `http://127.0.0.1:5000/api/health/database`; a successful connection returns `{"database":"ok"}`.

## Local and S3 image storage

Choose the mode in `.env`:

```env
# S3 bucket configured ho to S3; otherwise local storage.
STORAGE_BACKEND=auto

# Always save inside instance/uploads:
# STORAGE_BACKEND=local

# Always require S3:
# STORAGE_BACKEND=s3
```

Local mode needs no AWS credentials. Images are saved in `instance/uploads` and served through `/uploads/...`. In `auto` mode, an S3 upload failure falls back to local storage for that image.

## Production

Set `DATABASE_URL` to PostgreSQL, configure the AWS/S3 variables, run `flask db upgrade`, and start with:

```powershell
gunicorn app:app
```

For a public bucket or CDN, set `S3_PUBLIC_BASE_URL`. For a private bucket, leave it blank and the API will issue temporary signed image URLs.
