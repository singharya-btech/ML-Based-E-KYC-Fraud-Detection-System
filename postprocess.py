from datetime import datetime
import re


_DATE_FORMATS = (
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%Y-%m-%d",
    "%d %b %Y",
    "%d %B %Y",
)
_FIELD_MARKERS = {
    "NAME",
    "FATHER",
    "FATHER S",
    "FATHERS",
    "DOB",
    "DATE OF BIRTH",
    "YOB",
    "YEAR OF BIRTH",
    "GENDER",
    "MALE",
    "FEMALE",
    "PERMANENT ACCOUNT NUMBER",
}


def _tokens(data_string):
    return [token.strip() for token in data_string.split("|") if token.strip()]


def _normalized(token):
    return re.sub(r"[^A-Z0-9]+", " ", token.upper()).strip()


def _windows(tokens, size=3):
    for width in range(1, min(size, len(tokens)) + 1):
        for start in range(len(tokens) - width + 1):
            yield " ".join(tokens[start:start + width])


def _find_pan_number(tokens):
    for candidate in _windows(tokens):
        normalized = re.sub(r"[^A-Z0-9]", "", candidate.upper())
        match = re.search(r"[A-Z]{5}[0-9]{4}[A-Z]", normalized)
        if match:
            return match.group(0)
    return ""


def _find_aadhaar_number(tokens):
    for candidate in _windows(tokens):
        digits = re.sub(r"\D", "", candidate)
        if len(digits) == 12:
            return digits
    return ""


def _parse_date(tokens):
    for candidate in _windows(tokens):
        normalized = re.sub(r"\s+", " ", candidate.strip(" ,|"))
        for date_format in _DATE_FORMATS:
            try:
                return datetime.strptime(normalized, date_format)
            except ValueError:
                continue
    return None


def _value_after_label(tokens, label_pattern, forbidden_pattern=None):
    for index, token in enumerate(tokens):
        normalized = _normalized(token)
        if forbidden_pattern and re.search(forbidden_pattern, normalized):
            continue
        match = re.search(label_pattern, normalized)
        if not match:
            continue

        tail = normalized[match.end():].strip()
        if tail and tail not in _FIELD_MARKERS:
            return tail.title()

        for following in tokens[index + 1:]:
            value = following.strip(" :,-")
            if not value:
                continue
            if _normalized(value) in _FIELD_MARKERS:
                break
            if _parse_date([value]) or _find_pan_number([value]) or _find_aadhaar_number([value]):
                break
            return value
    return ""


def _find_name(tokens):
    return _value_after_label(tokens, r"\bNAME\b", r"\bFATHER\b")


def _find_gender(tokens):
    for token in tokens:
        normalized = _normalized(token)
        if normalized in {"MALE", "M"}:
            return "Male"
        if normalized in {"FEMALE", "F"}:
            return "Female"
    return ""


def _find_year_of_birth(tokens):
    for index, token in enumerate(tokens):
        normalized = _normalized(token)
        if normalized in {"YOB", "YEAR OF BIRTH"}:
            candidates = tokens[index + 1:index + 3]
        elif normalized == "DOB":
            candidates = tokens[index + 1:index + 2]
        else:
            continue
        for candidate in candidates:
            match = re.search(r"\b((?:19|20)\d{2})\b", candidate)
            if match:
                return match.group(1)
    return ""


def extract_information(data_string):
    tokens = _tokens(data_string)
    return {
        "ID": _find_pan_number(tokens),
        "Name": _find_name(tokens),
        "Father's Name": _value_after_label(
            tokens,
            r"\bFATHER(?:S|\s+S)?\s+NAME\b",
        ),
        "DOB": _parse_date(tokens),
        "ID Type": "PAN",
    }


def extract_information1(data_string):
    tokens = _tokens(data_string)
    dob = _parse_date(tokens)
    if dob is None:
        dob = _find_year_of_birth(tokens)

    name = _find_name(tokens)
    if not name:
        for index, token in enumerate(tokens):
            if _normalized(token) in {"DOB", "DATE OF BIRTH", "YOB", "YEAR OF BIRTH"} and index:
                candidate = tokens[index - 1].strip(" :,-")
                if _normalized(candidate) not in _FIELD_MARKERS:
                    name = candidate
                break

    return {
        "ID": _find_aadhaar_number(tokens),
        "Name": name,
        "Gender": _find_gender(tokens),
        "DOB": dob,
        "ID Type": "AADHAAR",
    }
