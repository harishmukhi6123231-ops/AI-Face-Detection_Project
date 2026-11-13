"""Run live face detection from the default webcam. Press Q to quit."""
import cv2

from detector import _cascade_path


def main() -> None:
    cascade = cv2.CascadeClassifier(_cascade_path())
    if cascade.empty():
        raise RuntimeError("Could not load the face detection model.")
    camera = cv2.VideoCapture(0)
    if not camera.isOpened():
        raise RuntimeError("Could not open the webcam.")
    try:
        while True:
            ok, frame = camera.read()
            if not ok:
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            for (x, y, width, height) in cascade.detectMultiScale(gray, 1.1, 5, minSize=(30, 30)):
                cv2.rectangle(frame, (x, y), (x + width, y + height), (55, 210, 145), 2)
            cv2.imshow("Face Finder · press Q to quit", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
