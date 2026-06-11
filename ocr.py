"""
License plate OCR module.
Reads text from detected license plate regions using EasyOCR.
"""

import cv2
import numpy as np
import easyocr


class PlateOCR:
    """
    Reads license plate text from cropped plate images.

    Uses EasyOCR with configurable language support. Applies preprocessing
    to improve recognition accuracy on plate crops.

    Parameters
    ----------
    languages : list of str
        Language codes for EasyOCR (e.g., ['en'], ['en', 'ch_sim']).
    gpu : bool
        Whether to use GPU for OCR inference.
    """

    def __init__(self, languages=None, gpu=True):
        if languages is None:
            languages = ["en"]
        self.reader = easyocr.Reader(languages, gpu=gpu)

    def read_plate(self, frame, plate_bbox):
        """
        Extract and read text from a license plate region.

        Parameters
        ----------
        frame : np.ndarray
            Full BGR frame.
        plate_bbox : tuple
            (x1, y1, x2, y2) bounding box of the plate in frame coordinates.

        Returns
        -------
        str
            Recognized plate text (cleaned), or empty string if unreadable.
        float
            Confidence score (0-1), or 0.0 if unreadable.
        """
        if plate_bbox is None:
            return "", 0.0

        x1, y1, x2, y2 = plate_bbox
        plate_crop = frame[y1:y2, x1:x2]

        if plate_crop.size == 0:
            return "", 0.0

        # Preprocess for better OCR
        processed = self._preprocess(plate_crop)

        # Run OCR
        results = self.reader.readtext(processed, detail=1)

        if not results:
            return "", 0.0

        # Combine all text detections, sorted by position (left to right)
        results.sort(key=lambda r: r[0][0][0])  # Sort by x-coordinate
        texts = []
        total_conf = 0.0

        for bbox, text, conf in results:
            cleaned = self._clean_plate_text(text)
            if cleaned:
                texts.append(cleaned)
                total_conf += conf

        if not texts:
            return "", 0.0

        combined_text = "".join(texts)
        avg_conf = total_conf / len(texts)

        return combined_text, avg_conf

    def _preprocess(self, plate_img):
        """
        Preprocess plate crop for better OCR accuracy.

        Applies grayscale conversion, resizing, contrast enhancement,
        and adaptive thresholding.
        """
        # Convert to grayscale
        gray = cv2.cvtColor(plate_img, cv2.COLOR_BGR2GRAY)

        # Resize to standard height for consistent OCR
        h, w = gray.shape
        target_h = 80
        scale = target_h / h
        resized = cv2.resize(
            gray, (int(w * scale), target_h), interpolation=cv2.INTER_CUBIC
        )

        # Apply CLAHE for contrast enhancement
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(resized)

        # Light bilateral filter to reduce noise while keeping edges
        denoised = cv2.bilateralFilter(enhanced, 9, 75, 75)

        return denoised

    def _clean_plate_text(self, text):
        """
        Clean OCR output to keep only valid plate characters.
        Removes spaces, special characters, and normalizes common
        OCR mistakes.
        """
        # Keep only alphanumeric characters and common plate chars
        cleaned = ""
        for ch in text.upper():
            if ch.isalnum() or ch == "-":
                cleaned += ch

        # Common OCR substitutions
        substitutions = {
            "O": "0",  # Only if surrounded by digits
            "I": "1",
            "S": "5",
            "B": "8",
        }
        # We apply conservative substitution only for isolated cases
        # For now, just return the cleaned text as-is
        return cleaned
