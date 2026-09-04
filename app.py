import os
import ssl
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

import boto3
from botocore.config import Config as BotoConfig
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, send_from_directory, url_for
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import URL, select, text
from werkzeug.exceptions import RequestEntityTooLarge

load_dotenv()

db = SQLAlchemy()
migrate = Migrate()

ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
MAX_IMAGES_PER_PLACE = 8


def database_uri():
    explicit_url = os.getenv("DATABASE_URL", "").strip()
    if explicit_url:
        return explicit_url.replace("postgres://", "postgresql+psycopg://", 1)

    host = os.getenv("DB_HOST", "").strip()
    if host:
        return URL.create(
            drivername="mysql+pymysql",
            username=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            host=host,
            port=int(os.getenv("DB_PORT", "3306")),
            database=os.getenv("DB_NAME"),
            query={"charset": "utf8mb4"},
        ).render_as_string(hide_password=False)

    return "sqlite:///wandershare.db"


def database_engine_options():
    options = {"pool_pre_ping": True, "pool_recycle": 280}
    certificate = os.getenv("DB_SSL_CA", "").strip()
    if certificate:
        options["connect_args"] = {
            "ssl": ssl.create_default_context(cafile=certificate)
        }
    return options


class Place(db.Model):
    __tablename__ = "places"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    location = db.Column(db.String(180), nullable=False, index=True)
    experience = db.Column(db.Text, nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    images = db.relationship(
        "PlaceImage",
        back_populates="place",
        cascade="all, delete-orphan",
        order_by="PlaceImage.position",
    )


class PlaceImage(db.Model):
    __tablename__ = "place_images"

    id = db.Column(db.Integer, primary_key=True)
    place_id = db.Column(
        db.Integer,
        db.ForeignKey("places.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    object_key = db.Column(db.String(600), nullable=False, unique=True)
    content_type = db.Column(db.String(80), nullable=False)
    position = db.Column(db.SmallInteger, nullable=False, default=0)
    place = db.relationship("Place", back_populates="images")


def create_app():
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI=database_uri(),
        SQLALCHEMY_ENGINE_OPTIONS=database_engine_options(),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH=int(os.getenv("MAX_UPLOAD_MB", "50")) * 1024 * 1024,
        JSON_SORT_KEYS=False,
        UPLOAD_FOLDER=os.getenv("LOCAL_UPLOAD_FOLDER")
        or os.path.join(app.instance_path, "uploads"),
    )

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)

    # Zero-setup local development. In production, set AUTO_CREATE_DB=0 and
    # apply versioned migrations with `flask db upgrade` during deployment.
    if os.getenv("AUTO_CREATE_DB", "1") == "1":
        with app.app_context():
            db.create_all()

    @app.get("/")
    def home():
        return render_template("index.html")

    @app.get("/visits")
    def visits():
        return render_template("visits.html")

    @app.get("/uploads/<path:filename>")
    def uploaded_file(filename):
        return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

    @app.get("/api/places")
    def list_places():
        places = db.session.scalars(
            select(Place).order_by(Place.created_at.desc(), Place.id.desc())
        ).unique().all()
        return jsonify([serialize_place(place) for place in places])

    @app.get("/api/health/database")
    def database_health():
        try:
            db.session.execute(text("SELECT 1"))
            return jsonify({"database": "ok"})
        except Exception:
            app.logger.exception("Database health check failed")
            return jsonify({"database": "unavailable"}), 503

    @app.post("/api/places")
    def create_place():
        name = request.form.get("name", "").strip()
        location = request.form.get("location", "").strip()
        experience = request.form.get("experience", "").strip()
        files = [item for item in request.files.getlist("photos") if item.filename]

        errors = {}
        if not name or len(name) > 120:
            errors["name"] = "Name is required and must be under 120 characters."
        if not location or len(location) > 180:
            errors["location"] = "Location is required and must be under 180 characters."
        if not experience or len(experience) > 5000:
            errors["experience"] = "Experience is required and must be under 5,000 characters."
        if len(files) > MAX_IMAGES_PER_PLACE:
            errors["photos"] = f"Upload no more than {MAX_IMAGES_PER_PLACE} images."

        for image in files:
            if image.mimetype not in ALLOWED_IMAGE_TYPES:
                errors["photos"] = "Only JPG, PNG, WebP, and GIF images are allowed."
                break

        if errors:
            return jsonify({"error": "Please correct the form.", "fields": errors}), 400

        uploaded_keys = []

        try:
            place = Place(name=name, location=location, experience=experience)
            db.session.add(place)
            db.session.flush()

            for position, image in enumerate(files):
                extension = ALLOWED_IMAGE_TYPES[image.mimetype]
                object_key = store_image(image, place.id, extension, app)
                uploaded_keys.append(object_key)
                db.session.add(
                    PlaceImage(
                        place=place,
                        object_key=object_key,
                        content_type=image.mimetype,
                        position=position,
                    )
                )

            db.session.commit()
            return jsonify(serialize_place(place)), 201
        except Exception:
            db.session.rollback()
            for object_key in uploaded_keys:
                try:
                    delete_image(object_key, app)
                except Exception:
                    app.logger.exception("Could not clean up image %s", object_key)
            app.logger.exception("Place creation failed")
            return jsonify({"error": "The place could not be saved. Please try again."}), 500

    @app.errorhandler(RequestEntityTooLarge)
    def upload_too_large(_error):
        return jsonify({"error": "The upload is larger than the server limit."}), 413

    @app.errorhandler(500)
    def internal_error(_error):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Internal server error. Check the Flask terminal."}), 500
        return "Internal server error.", 500

    @app.errorhandler(404)
    def not_found(_error):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Not found."}), 404
        return render_template("index.html"), 404

    return app


def get_s3_client():
    bucket = os.getenv("S3_BUCKET")
    if not bucket:
        raise RuntimeError("S3_BUCKET is required when uploading images.")

    return boto3.client(
        "s3",
        region_name=os.getenv("AWS_REGION", "ap-south-1"),
        endpoint_url=os.getenv("S3_ENDPOINT_URL") or None,
        config=BotoConfig(signature_version="s3v4"),
    )


def selected_storage_backend():
    backend = os.getenv("STORAGE_BACKEND", "auto").lower().strip()
    if backend not in {"auto", "local", "s3"}:
        raise RuntimeError("STORAGE_BACKEND must be auto, local, or s3.")
    if backend == "auto":
        return "s3" if os.getenv("S3_BUCKET") else "local"
    return backend


def store_image(image, place_id, extension, app):
    relative_key = f"places/{place_id}/{uuid.uuid4().hex}{extension}"
    backend = selected_storage_backend()

    if backend == "s3":
        try:
            image.stream.seek(0)
            get_s3_client().upload_fileobj(
                image.stream,
                os.environ["S3_BUCKET"],
                relative_key,
                ExtraArgs={"ContentType": image.mimetype},
            )
            return f"s3:{relative_key}"
        except Exception:
            if os.getenv("STORAGE_BACKEND", "auto").lower().strip() != "auto":
                raise
            app.logger.warning("S3 upload failed; saving this image locally instead.")

    local_path = os.path.join(app.config["UPLOAD_FOLDER"], *relative_key.split("/"))
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    image.stream.seek(0)
    image.save(local_path)
    return f"local:{relative_key}"


def delete_image(object_key, app):
    if object_key.startswith("local:"):
        relative_key = object_key.removeprefix("local:")
        upload_root = os.path.abspath(app.config["UPLOAD_FOLDER"])
        local_path = os.path.abspath(
            os.path.join(upload_root, *relative_key.split("/"))
        )
        if os.path.commonpath([upload_root, local_path]) != upload_root:
            raise ValueError("Unsafe local upload path.")
        try:
            os.remove(local_path)
        except FileNotFoundError:
            pass
        return

    relative_key = object_key.removeprefix("s3:")
    get_s3_client().delete_object(Bucket=os.environ["S3_BUCKET"], Key=relative_key)


def image_url(image):
    if image.object_key.startswith("local:"):
        return url_for(
            "uploaded_file",
            filename=image.object_key.removeprefix("local:"),
        )

    object_key = image.object_key.removeprefix("s3:")
    public_base = os.getenv("S3_PUBLIC_BASE_URL", "").rstrip("/")
    if public_base:
        return f"{public_base}/{quote(object_key, safe='/')}"

    return get_s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": os.environ["S3_BUCKET"], "Key": object_key},
        ExpiresIn=int(os.getenv("S3_SIGNED_URL_TTL", "3600")),
    )


def serialize_place(place):
    return {
        "id": place.id,
        "name": place.name,
        "location": place.location,
        "experience": place.experience,
        "images": [image_url(image) for image in place.images],
        "created_at": place.created_at.isoformat(),
    }


app = create_app()


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1")
