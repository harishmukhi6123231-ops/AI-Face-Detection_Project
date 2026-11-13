"""Flask app for camera attendance and group-photo face recognition."""
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import base64
import json
import shutil
import sqlite3
from uuid import uuid4

import cv2
import numpy as np
from flask import Flask, flash, jsonify, redirect, render_template, request, send_from_directory, url_for
from werkzeug.utils import secure_filename

from detector import analyze_image, InvalidImageError

ROOT = Path(__file__).resolve().parent
UPLOAD_DIR = ROOT / "static" / "uploads"
RESULT_DIR = ROOT / "results"
REGISTERED_DIR = ROOT / "static" / "registered_faces"
PENDING_DIR = ROOT / "static" / "pending_faces"
DATABASE = ROOT / "faces.db"
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
MATCH_THRESHOLD = 0.45

app = Flask(__name__)
app.config["SECRET_KEY"] = "local-face-finder"
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
RESULT_DIR.mkdir(parents=True, exist_ok=True)
REGISTERED_DIR.mkdir(parents=True, exist_ok=True)
PENDING_DIR.mkdir(parents=True, exist_ok=True)


@contextmanager
def db_connection():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


with db_connection() as connection:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS people (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            embedding TEXT NOT NULL,
            person_id TEXT,
            branch_course TEXT,
            contact TEXT,
            photo_filename TEXT
        )"""
    )
    existing_columns = {row["name"] for row in connection.execute("PRAGMA table_info(people)")}
    for column, sql_type in (("person_id", "TEXT"), ("branch_course", "TEXT"), ("contact", "TEXT"), ("photo_filename", "TEXT")):
        if column not in existing_columns:
            connection.execute(f"ALTER TABLE people ADD COLUMN {column} {sql_type}")
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_people_person_id ON people(person_id)")
    connection.execute(
        """CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY,
            person_name TEXT NOT NULL,
            attendance_date TEXT NOT NULL,
            attendance_time TEXT NOT NULL,
            UNIQUE(person_name, attendance_date)
        )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS pending_faces (
            token TEXT PRIMARY KEY,
            embedding TEXT NOT NULL,
            image_filename TEXT NOT NULL,
            created_at TEXT NOT NULL
        )"""
    )


def decode_camera_image():
    payload = request.get_json(silent=True) or {}
    image_data = payload.get("image", "")
    if not isinstance(image_data, str) or "," not in image_data:
        return None
    try:
        raw = base64.b64decode(image_data.split(",", 1)[1], validate=True)
        return cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    except (ValueError, cv2.error):
        return None


def face_matches(embedding):
    with db_connection() as connection:
        people = connection.execute("SELECT name, embedding FROM people").fetchall()
    candidate = np.asarray(embedding, dtype=np.float32)
    candidate /= max(float(np.linalg.norm(candidate)), 1e-12)
    best_name, best_score = None, -1.0
    for person in people:
        known = np.asarray(json.loads(person["embedding"]), dtype=np.float32)
        score = float(np.dot(candidate, known))
        if score > best_score:
            best_name, best_score = person["name"], score
    if best_score >= MATCH_THRESHOLD:
        return best_name, best_score
    return "Unknown", best_score


def face_embedding(face):
    embedding = getattr(face, "normed_embedding", None)
    return embedding if embedding is not None else face.embedding


def crop_face(image, bbox, padding_ratio=0.22):
    height, width = image.shape[:2]
    x1, y1, x2, y2 = (int(value) for value in bbox)
    pad_x = int((x2 - x1) * padding_ratio)
    pad_y = int((y2 - y1) * padding_ratio)
    x1, y1 = max(0, x1 - pad_x), max(0, y1 - pad_y)
    x2, y2 = min(width, x2 + pad_x), min(height, y2 + pad_y)
    return image[y1:y2, x1:x2].copy()


def details_complete(person):
    return all(person[key] for key in ("person_id", "branch_course", "contact"))


def record_attendance(name):
    now = datetime.now().astimezone()
    with db_connection() as connection:
        cursor = connection.execute(
            "INSERT OR IGNORE INTO attendance (person_name, attendance_date, attendance_time) VALUES (?, ?, ?)",
            (name, now.date().isoformat(), now.strftime("%H:%M:%S")),
        )
    return cursor.rowcount == 1


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/attendance")
def attendance_list():
    with db_connection() as connection:
        records = connection.execute(
            "SELECT id, person_name, attendance_date, attendance_time FROM attendance ORDER BY attendance_date DESC, attendance_time DESC"
        ).fetchall()
    return jsonify(
        records=[{
            "id": row["id"],
            "name": row["person_name"],
            "date": row["attendance_date"],
            "time": row["attendance_time"],
        } for row in records],
    )


@app.delete("/attendance/<int:record_id>")
def delete_attendance(record_id):
    with db_connection() as connection:
        cursor = connection.execute("DELETE FROM attendance WHERE id = ?", (record_id,))
    if cursor.rowcount == 0:
        return jsonify(error="Attendance record was not found."), 404
    return jsonify(message="Attendance record deleted.")


@app.delete("/attendance")
def clear_attendance():
    with db_connection() as connection:
        connection.execute("DELETE FROM attendance")
    return jsonify(message="Attendance history cleared.")


@app.post("/camera/recognize")
def recognize_camera_frame():
    image = decode_camera_image()
    if image is None:
        return jsonify(error="Could not read the camera frame. Please try again."), 400
    try:
        faces = analyze_image(image, check_liveness=True)
        mark_attendance = bool((request.get_json(silent=True) or {}).get("mark_attendance"))
        results = []
        for face in faces:
            liveness = getattr(face, "liveness", None)
            liveness_state = getattr(liveness, "status", "unavailable")
            live_score = getattr(liveness, "live_score", None)
            if liveness_state != "ok" or not bool(getattr(liveness, "is_live", False)):
                if liveness_state == "ok":
                    display_name, state = "Photo/screen rejected", "fake"
                elif liveness_state == "input_rejected":
                    display_name, state = "Move closer / center face", "input_rejected"
                else:
                    display_name, state = "Liveness check unavailable", "unavailable"
                results.append({
                    "name": display_name,
                    "bbox": [int(value) for value in face.bbox],
                    "liveness_status": state,
                    "live_score": round(float(live_score), 3) if live_score is not None else None,
                    "checked_in": False,
                    "needs_details": False,
                    "person_key": None,
                })
                continue

            name, score = face_matches(face_embedding(face))
            profile = None
            if name != "Unknown":
                with db_connection() as connection:
                    profile = connection.execute("SELECT * FROM people WHERE name = ?", (name,)).fetchone()
            needs_details = profile is not None and not details_complete(profile)
            checked_in = record_attendance(name) if mark_attendance and name != "Unknown" and not needs_details else False
            results.append({
                "name": name,
                "score": round(score, 3),
                "bbox": [int(value) for value in face.bbox],
                "checked_in": checked_in,
                "liveness_status": "live",
                "live_score": round(float(live_score), 3) if live_score is not None else None,
                "needs_details": needs_details,
                "person_key": profile["id"] if needs_details else None,
                "profile_image": url_for("registered_image", filename=profile["photo_filename"]) if needs_details and profile["photo_filename"] else None,
            })
        return jsonify(faces=results, width=image.shape[1], height=image.shape[0])
    except Exception:
        app.logger.exception("Camera face recognition failed")
        return jsonify(error="Face scan failed. Please try again."), 500


@app.post("/camera/register")
def register_camera_face():
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", "")).strip()
    person_id = str(payload.get("person_id", "")).strip()
    branch_course = str(payload.get("branch_course", "")).strip()
    contact = str(payload.get("contact", "")).strip()
    image = decode_camera_image()
    if not name or len(name) > 80:
        return jsonify(error="Enter a name of 1 to 80 characters."), 400
    if not person_id or len(person_id) > 50:
        return jsonify(error="Enter an ID of 1 to 50 characters."), 400
    if not branch_course or len(branch_course) > 100:
        return jsonify(error="Enter a branch or course of 1 to 100 characters."), 400
    if not contact or len(contact) > 30:
        return jsonify(error="Enter a contact value of 1 to 30 characters."), 400
    if image is None:
        return jsonify(error="Could not read the camera frame. Please try again."), 400
    try:
        faces = analyze_image(image, check_liveness=True)
        if len(faces) != 1:
            return jsonify(error="Please frame exactly one face to register."), 400
        liveness = getattr(faces[0], "liveness", None)
        if liveness is None or liveness.status != "ok" or not liveness.is_live:
            if liveness is not None and liveness.status == "input_rejected":
                return jsonify(error="Liveness check could not verify the face. Move closer to the center and try again."), 422
            return jsonify(error="The camera did not verify a live person. Please use the camera directly and try again."), 422
        serialized = json.dumps(np.asarray(face_embedding(faces[0]), dtype=np.float32).tolist())
        photo_filename = f"{uuid4().hex}.jpg"
        photo_path = REGISTERED_DIR / photo_filename
        face_crop = crop_face(image, faces[0].bbox)
        if face_crop.size == 0 or not cv2.imwrite(str(photo_path), face_crop):
            return jsonify(error="Could not save the captured face image."), 500
        with db_connection() as connection:
            connection.execute(
                "INSERT INTO people (name, embedding, person_id, branch_course, contact, photo_filename) VALUES (?, ?, ?, ?, ?, ?)",
                (name, serialized, person_id, branch_course, contact, photo_filename),
            )
        return jsonify(message=f"{name} is registered. Look at the camera to identify them.")
    except sqlite3.IntegrityError:
        if "photo_path" in locals():
            photo_path.unlink(missing_ok=True)
        return jsonify(error="That name or ID is already registered. Check the details and try again."), 409
    except Exception:
        if "photo_path" in locals():
            photo_path.unlink(missing_ok=True)
        app.logger.exception("Camera face registration failed")
        return jsonify(error="Registration failed. Please try again."), 500


@app.get("/people")
def list_people():
    with db_connection() as connection:
        people = connection.execute(
            "SELECT id, name, person_id, branch_course, contact, photo_filename FROM people ORDER BY name COLLATE NOCASE"
        ).fetchall()
    return jsonify(people=[{
        "id": person["id"],
        "name": person["name"],
        "person_id": person["person_id"] or "",
        "branch_course": person["branch_course"] or "",
        "contact": person["contact"] or "",
        "image_url": url_for("registered_image", filename=person["photo_filename"]) if person["photo_filename"] else None,
        "details_complete": details_complete(person),
    } for person in people])


@app.get("/registered-images/<path:filename>")
def registered_image(filename):
    return send_from_directory(REGISTERED_DIR, filename, as_attachment=False)


@app.get("/pending-images/<path:filename>")
def pending_image(filename):
    return send_from_directory(PENDING_DIR, filename, as_attachment=False)


def profile_fields(payload):
    return {
        "name": str(payload.get("name", "")).strip(),
        "person_id": str(payload.get("person_id", "")).strip(),
        "branch_course": str(payload.get("branch_course", "")).strip(),
        "contact": str(payload.get("contact", "")).strip(),
    }


def validate_profile(fields):
    limits = {"name": 80, "person_id": 50, "branch_course": 100, "contact": 30}
    for key, limit in limits.items():
        if not fields[key] or len(fields[key]) > limit:
            return f"Enter {key.replace('_', ' ')} (up to {limit} characters)."
    return None


@app.patch("/people/<int:person_key>")
def update_person(person_key):
    fields = profile_fields(request.get_json(silent=True) or {})
    error = validate_profile(fields)
    if error:
        return jsonify(error=error), 400
    try:
        with db_connection() as connection:
            existing = connection.execute("SELECT name FROM people WHERE id = ?", (person_key,)).fetchone()
            if existing is None:
                return jsonify(error="Person was not found."), 404
            connection.execute(
                "UPDATE people SET name = ?, person_id = ?, branch_course = ?, contact = ? WHERE id = ?",
                (fields["name"], fields["person_id"], fields["branch_course"], fields["contact"], person_key),
            )
            if existing["name"] != fields["name"]:
                connection.execute("UPDATE attendance SET person_name = ? WHERE person_name = ?", (fields["name"], existing["name"]))
        return jsonify(message=f"Details for {fields['name']} were updated.")
    except sqlite3.IntegrityError:
        return jsonify(error="That name or ID is already used by another person."), 409


@app.delete("/people/<int:person_key>")
def delete_person(person_key):
    with db_connection() as connection:
        person = connection.execute("SELECT name, photo_filename FROM people WHERE id = ?", (person_key,)).fetchone()
        if person is None:
            return jsonify(error="Person was not found."), 404
        connection.execute("DELETE FROM attendance WHERE person_name = ?", (person["name"],))
        connection.execute("DELETE FROM people WHERE id = ?", (person_key,))
    if person["photo_filename"]:
        (REGISTERED_DIR / Path(person["photo_filename"]).name).unlink(missing_ok=True)
    return jsonify(message=f"{person['name']} and their stored face image were deleted.")


@app.post("/photo/register")
def register_photo_face():
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", "")).strip()
    token = str(payload.get("token", ""))
    if not name or len(name) > 80:
        return jsonify(error="Enter a name of 1 to 80 characters."), 400
    if len(token) != 32 or any(char not in "0123456789abcdef" for char in token):
        return jsonify(error="This face registration link is invalid. Scan the photo again."), 400
    with db_connection() as connection:
        pending = connection.execute("SELECT * FROM pending_faces WHERE token = ?", (token,)).fetchone()
    if pending is None:
        return jsonify(error="This face is no longer available. Scan the photo again."), 404

    pending_path = PENDING_DIR / Path(pending["image_filename"]).name
    if not pending_path.is_file():
        return jsonify(error="The captured face image is missing. Scan the photo again."), 404
    photo_filename = f"{uuid4().hex}.jpg"
    registered_path = REGISTERED_DIR / photo_filename
    try:
        shutil.copy2(pending_path, registered_path)
        with db_connection() as connection:
            connection.execute(
                "INSERT INTO people (name, embedding, person_id, branch_course, contact, photo_filename) VALUES (?, ?, NULL, NULL, NULL, ?)",
                (name, pending["embedding"], photo_filename),
            )
            connection.execute("DELETE FROM pending_faces WHERE token = ?", (token,))
        pending_path.unlink(missing_ok=True)
        return jsonify(message=f"{name} was registered. Attendance will ask for their details before check-in.")
    except sqlite3.IntegrityError:
        registered_path.unlink(missing_ok=True)
        return jsonify(error="That name is already registered. Use a different name."), 409
    except Exception:
        registered_path.unlink(missing_ok=True)
        app.logger.exception("Group photo face registration failed")
        return jsonify(error="Could not register this face. Please try again."), 500


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.post("/detect")
def detect():
    image_file = request.files.get("image")
    if image_file is None or not image_file.filename:
        flash("Choose a group photo to upload.")
        return redirect(url_for("index"))
    safe_name = secure_filename(image_file.filename)
    if not allowed_file(safe_name):
        flash("Please upload a JPG, PNG, or WEBP image.")
        return redirect(url_for("index"))

    token = uuid4().hex
    upload_path = UPLOAD_DIR / f"{token}{Path(safe_name).suffix.lower()}"
    result_name = f"{token}.jpg"
    result_path = RESULT_DIR / result_name
    image_file.save(upload_path)
    try:
        image = cv2.imread(str(upload_path))
        if image is None:
            raise InvalidImageError("This file could not be read as an image. Try another photo.")
        faces = analyze_image(image)
        results = []
        unknown_items = []
        for face in faces:
            name, score = face_matches(face_embedding(face))
            x1, y1, x2, y2 = (int(value) for value in face.bbox)
            color = (55, 210, 145) if name != "Unknown" else (120, 190, 255)
            cv2.rectangle(image, (x1, y1), (x2, y2), color, 3)
            cv2.putText(image, name, (x1, max(y1 - 10, 24)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2, cv2.LINE_AA)
            results.append({"name": name, "score": round(score, 3)})
            if name == "Unknown":
                token = uuid4().hex
                image_filename = f"{token}.jpg"
                pending_path = PENDING_DIR / image_filename
                face_crop = crop_face(cv2.imread(str(upload_path)), face.bbox)
                if face_crop.size == 0 or not cv2.imwrite(str(pending_path), face_crop):
                    raise OSError("Could not save an unknown face crop.")
                with db_connection() as connection:
                    connection.execute(
                        "INSERT INTO pending_faces (token, embedding, image_filename, created_at) VALUES (?, ?, ?, ?)",
                        (token, json.dumps(np.asarray(face_embedding(face), dtype=np.float32).tolist()), image_filename, datetime.now().astimezone().isoformat()),
                    )
                unknown_items.append({"token": token, "image_url": url_for("pending_image", filename=image_filename)})
        if not cv2.imwrite(str(result_path), image):
            raise OSError("Could not save the recognition result.")
    except InvalidImageError as exc:
        upload_path.unlink(missing_ok=True)
        flash(str(exc))
        return redirect(url_for("index"))
    except Exception:
        upload_path.unlink(missing_ok=True)
        app.logger.exception("Photo recognition failed")
        flash("Photo recognition failed. Check the image and try again.")
        return redirect(url_for("index"))

    known_count = sum(1 for result in results if result["name"] != "Unknown")
    return render_template(
        "result.html",
        result_name=result_name,
        count=len(results),
        results=results,
        known_count=known_count,
        unknown_items=unknown_items,
    )


@app.get("/results/<path:filename>")
def result_file(filename: str):
    return send_from_directory(RESULT_DIR, filename, as_attachment=False)


@app.errorhandler(413)
def too_large(_error):
    flash("The image is too large. Please choose an image under 12 MB.")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True)
