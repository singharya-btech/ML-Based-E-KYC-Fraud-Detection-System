import cv2
import os
import logging
import math
import numpy as np
from utils import read_yaml

logging_str = "[%(asctime)s: %(levelname)s: %(module)s]: %(message)s"
log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)
logging.basicConfig(filename=os.path.join(log_dir,"ekyc_logs.log"), level=logging.INFO, format=logging_str, filemode="a")


project_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(project_dir, "config.yaml")
config = read_yaml(config_path)

artifacts = config['artifacts']
cascade_path = artifacts['HAARCASCADE_PATH']
if not os.path.isabs(cascade_path):
    cascade_path = os.path.join(project_dir, cascade_path)
MIN_FACE_SIDE_PX = 80
MODEL_FACE_SIDE_PX = 160


class FaceQualityError(ValueError):
    pass


def detect_and_extract_face(img):
    logging.info("Extracting face...")
    if img is None:
        logging.warning("Cannot detect a face in an empty image")
        return None
    if not isinstance(img, np.ndarray) or img.size == 0:
        raise FaceQualityError("Image must be a non-empty decoded image.")
    if img.dtype != np.uint8:
        raise FaceQualityError("Image must use 8-bit pixel values.")

    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    elif img.ndim == 3 and img.shape[2] == 4:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    elif img.ndim != 3 or img.shape[2] != 3:
        raise FaceQualityError("Image must be grayscale, BGR, or BGRA.")
    if min(img.shape[:2]) < 32:
        raise FaceQualityError("Image is too small to detect a face reliably.")

    gray_img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    face_cascade = cv2.CascadeClassifier(cascade_path)
    if face_cascade.empty() is True:
        raise RuntimeError(f"Could not load the face detector model at {cascade_path}.")

    try:
        faces = face_cascade.detectMultiScale(gray_img, scaleFactor=1.1, minNeighbors=5)
    except cv2.error as exc:
        raise FaceQualityError("The face detector could not process this image.") from exc

    if len(faces) == 0:
        logging.warning("No face detected in the image")
        return None

    x, y, width, height = max(faces, key=lambda box: box[2] * box[3])
    if min(width, height) < MIN_FACE_SIDE_PX:
        raise FaceQualityError(
            f"Detected face is only {width}x{height} source pixels; at least "
            f"{MIN_FACE_SIDE_PX}x{MIN_FACE_SIDE_PX} pixels are required."
        )

    margin = int(round(max(width, height) * 0.25))
    left = max(0, x - margin)
    top = max(0, y - margin)
    right = min(img.shape[1], x + width + margin)
    bottom = min(img.shape[0], y + height + margin)
    face_crop = img[top:bottom, left:right]
    if face_crop.size == 0:
        raise FaceQualityError("The detected face crop is empty.")

    if min(face_crop.shape[:2]) < MODEL_FACE_SIDE_PX:
        target_size = (
            max(MODEL_FACE_SIDE_PX, face_crop.shape[1]),
            max(MODEL_FACE_SIDE_PX, face_crop.shape[0]),
        )
        face_crop = cv2.resize(face_crop, target_size, interpolation=cv2.INTER_CUBIC)

    logging.info("Detected face crop in memory with model dimensions %s", face_crop.shape[:2])
    return face_crop

def deepface_face_comparison(image1_path, image2_path):
    from deepface import DeepFace

    if image1_path is None or image2_path is None:
        raise ValueError("Both face crops are required")
    for image in (image1_path, image2_path):
        if not isinstance(image, np.ndarray) or image.size == 0:
            raise ValueError("Face comparison requires two non-empty image arrays")
        if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
            raise ValueError("Face crops must be 8-bit BGR images")

    verification = DeepFace.verify(
        img1_path=image1_path,
        img2_path=image2_path,
        model_name="Facenet",
        detector_backend="skip",
    )

    if not isinstance(verification, dict) or not isinstance(verification.get("verified"), bool):
        raise RuntimeError("Face model returned an invalid verification result")
    for score_name in ("distance", "threshold"):
        score = verification.get(score_name)
        if score is not None and not math.isfinite(float(score)):
            raise RuntimeError(f"Face model returned an invalid {score_name} score")

    if verification["verified"]:
        logging.info("Faces are verified as the same person")
    else:
        logging.info(
            "Faces did not match: distance=%s threshold=%s",
            verification.get("distance"),
            verification.get("threshold"),
        )
    return verification
    
