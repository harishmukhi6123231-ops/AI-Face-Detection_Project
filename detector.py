"""Face detection and annotation using the InsightFace buffalo_l model."""
from functools import lru_cache
from pathlib import Path

import cv2
from insightface.app import FaceAnalysis

PROJECT_ROOT = Path(__file__).resolve().parent


class InvalidImageError(ValueError):
    """Raised when an uploaded file cannot be decoded as an image."""


@lru_cache(maxsize=2)
def _face_analyzer(check_liveness: bool = False) -> FaceAnalysis:
    """Load InsightFace once per mode and reuse it for subsequent images."""
    options = {}
    if check_liveness:
        options.update(addons=["liveness"], liveness_mode="normal", liveness_threshold=0.8)
    analyzer = FaceAnalysis(
        name="buffalo_l",
        root=str(PROJECT_ROOT),
        providers=["CPUExecutionProvider"],
        **options,
    )
    analyzer.prepare(ctx_id=-1, det_size=(640, 640))
    return analyzer


def detect_faces(image_path: str | Path, output_path: str | Path) -> int:
    """Detect faces with InsightFace, save a boxed image, and return the count."""
    image = cv2.imread(str(image_path))
    if image is None:
        raise InvalidImageError("This file could not be read as an image. Try another photo.")

    faces = _face_analyzer(check_liveness=False).get(image)
    for face in faces:
        x1, y1, x2, y2 = (int(value) for value in face.bbox)
        cv2.rectangle(image, (x1, y1), (x2, y2), (55, 210, 145), 3)

        # Show confidence to make it clear these boxes are detections, not names.
        score = float(face.det_score)
        label = f"Face {score:.2f}"
        text_y = max(y1 - 10, 24)
        cv2.putText(
            image,
            label,
            (x1, text_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (55, 210, 145),
            2,
            cv2.LINE_AA,
        )

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(destination), image):
        raise OSError("Could not save the annotated image.")
    return len(faces)


def analyze_image(image, check_liveness: bool = False):
    """Analyze an image, optionally requiring a live face before recognition."""
    return _face_analyzer(check_liveness=check_liveness).get(image)
