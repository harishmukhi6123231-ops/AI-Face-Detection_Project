# Face Finder

Flask app for local face recognition, camera attendance, and identifying people in group photos. It uses InsightFace's `buffalo_l` model pack.

## Model location

The face detector and recognition model are stored in `models/buffalo_l/` inside this project. Camera attendance and camera registration also use the separate RGB liveness add-on in `addons/liveness.onnx`. `detector.py` sets InsightFace's model root to the project directory, so both models load from this project.

The old `models/haarcascade_frontalface_default.xml` file is not used by the Flask app.

## Run the app

Use Python 3.10 or newer. From this directory, install dependencies and start Flask:

```bash
python -m pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000. Use the camera panel to check in or register a person. Upload a group photo to identify registered people and register unknown faces by name. The Registered people sidebar lists saved face images and profile details. Attendance is stored locally in `faces.db`.

## Project layout

```text
app.py                   Flask app and local registry endpoints
detector.py              InsightFace model loading and face analysis
webcam.py                Standalone webcam script
requirements.txt         Python dependencies
models/buffalo_l/        InsightFace model pack used by the app
addons/liveness.onnx     RGB liveness screening add-on for camera use
models/haarcascade_...   Legacy OpenCV cascade; not used by the Flask app
static/                  CSS, JavaScript, uploads, and saved face crops
templates/               Flask pages
results/                 Annotated group photo outputs
faces.db                 Local people and attendance database
```

## Model license

InsightFace's supplied pretrained model packs are for non-commercial research use. Review the [model licensing information](https://github.com/deepinsight/insightface/tree/master/model_zoo) for your intended use.

Liveness screening helps reject suspected photos or screen replays, but it is not a guarantee against every spoofing method. The liveness model is a separate InsightFace add-on and has its own applicable notices; review the [liveness guide](https://github.com/deepinsight/insightface/blob/master/python-package/docs/liveness.md).
