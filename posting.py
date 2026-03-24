import os
import sys
from http.cookiejar import MozillaCookieJar
from typing import Any, Dict, List, Optional, Tuple
from datetime import date, datetime
import requests
import json

def blankChargeCodeModel():
    return {
        "chargeCodeId": None,
        "chargeCodeName": None,
        "type": None,
        "hierarchicalName": None,
        "leave": False,
    }


def normalizeChargeCodeModel(model):
    if not isinstance(model, dict):
        return None

    charge_code_id = (
        model.get("chargeCodeId")
        or model.get("chargeCodeID")
        or model.get("CHARGECODEID")
    )
    charge_code_name = model.get("chargeCodeName")
    charge_code_type = model.get("type")
    hierarchical_name = model.get("hierarchicalName")
    leave = model.get("leave")

    normalized = {
        "chargeCodeId": charge_code_id,
        "chargeCodeName": charge_code_name,
        "type": charge_code_type,
        "hierarchicalName": hierarchical_name,
        "leave": bool(leave) if leave is not None else False,
    }

    if not any(value not in (None, "", False) for value in normalized.values()):
        return None

    return normalized


def hasChargeCodeValue(model):
    if not isinstance(model, dict):
        return False
    return any(
        model.get(key) not in (None, "", False)
        for key in ("chargeCodeId", "chargeCodeName", "hierarchicalName")
    ) or bool(model.get("leave"))


def inferChargeCodeSlot(model):
    if not isinstance(model, dict):
        return None

    kind = str(model.get("type") or "").strip().casefold().replace("_", " ")
    if kind == "customer":
        return 0
    if kind == "job":
        return 1
    if kind == "service item":
        return 2
    if kind == "class":
        return 3
    return None


def normalizeChargeCodeChunk(rawChunk, blankServiceItems=True):
    chunk = [blankChargeCodeModel() for _ in range(4)]
    deferred = []

    if not isinstance(rawChunk, list):
        return chunk

    for rawIndex, item in enumerate(rawChunk):
        normalized = normalizeChargeCodeModel(item)
        if normalized is None:
            normalized = blankChargeCodeModel()

        slot = inferChargeCodeSlot(normalized)
        if slot is not None and not hasChargeCodeValue(chunk[slot]):
            chunk[slot] = normalized
            continue

        deferred.append((rawIndex, normalized))

    for rawIndex, normalized in deferred:
        preferredSlots = []
        if 0 <= rawIndex < 4:
            preferredSlots.append(rawIndex)
        preferredSlots.extend(slot for slot in range(4) if slot not in preferredSlots)

        for slot in preferredSlots:
            if not hasChargeCodeValue(chunk[slot]):
                chunk[slot] = normalized
                break

    if blankServiceItems:
        chunk[2] = blankChargeCodeModel()

    return chunk


def chunkHasChargeCodeValue(chunk):
    if not isinstance(chunk, list):
        return False
    return any(hasChargeCodeValue(item) for item in chunk if isinstance(item, dict))


def splitChargeCodeModelsIntoChunks(models):
    chunks = []
    current = []
    currentSlots = set()
    currentHasValue = False

    def flushCurrent():
        nonlocal current, currentSlots, currentHasValue
        if not current:
            return
        chunk = normalizeChargeCodeChunk(current)
        if chunkHasChargeCodeValue(chunk):
            chunks.append(chunk)
        current = []
        currentSlots = set()
        currentHasValue = False

    if not isinstance(models, list):
        return chunks

    if models and all(isinstance(item, list) for item in models):
        for sub in models:
            chunk = normalizeChargeCodeChunk(sub)
            if chunkHasChargeCodeValue(chunk):
                chunks.append(chunk)
        return chunks

    for item in models:
        if isinstance(item, list):
            flushCurrent()
            chunk = normalizeChargeCodeChunk(item)
            if chunkHasChargeCodeValue(chunk):
                chunks.append(chunk)
            continue

        normalized = normalizeChargeCodeModel(item)
        slot = inferChargeCodeSlot(normalized) if normalized is not None else None
        shouldFlush = False

        if current:
            if slot == 0 and currentHasValue:
                shouldFlush = True
            elif slot is not None and slot in currentSlots and currentHasValue:
                shouldFlush = True
            elif len(current) >= 4:
                shouldFlush = True

        if shouldFlush:
            flushCurrent()

        current.append(item)
        if slot is not None:
            currentSlots.add(slot)
        if normalized is not None and hasChargeCodeValue(normalized):
            currentHasValue = True

    flushCurrent()
    return chunks


def chargeCodeModelSignature(model):
    normalized = normalizeChargeCodeModel(model)
    if normalized is None:
        return None
    return (
        normalized.get("chargeCodeId"),
        normalized.get("chargeCodeName"),
        normalized.get("type"),
        normalized.get("hierarchicalName"),
        bool(normalized.get("leave")),
    )


def chargeCodeChunkSignature(chunk, includeServiceItem=True):
    normalizedChunk = normalizeChargeCodeChunk(chunk)
    slots = range(4) if includeServiceItem else (0, 1, 3)
    return tuple(
        chargeCodeModelSignature(normalizedChunk[idx]) for idx in slots
    )


def extractChargeCodeChunksFromTimesheetPayload(payload):
    preferred = []
    fallback = []

    def visit(node):
        if isinstance(node, dict):
            for key, value in node.items():
                keyLower = str(key).strip().lower()

                if keyLower in {"chargecodeidmodels", "chargecodeidmodel"} and isinstance(value, list):
                    preferred.extend(splitChargeCodeModelsIntoChunks(value))
                    continue

                if keyLower == "chargecodes" and isinstance(value, list):
                    fallback.extend(splitChargeCodeModelsIntoChunks(value))
                    continue

                visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(payload)

    sourceChunks = preferred or fallback
    seen = set()
    results = []
    for chunk in sourceChunks:
        sig = chargeCodeChunkSignature(chunk)
        if sig in seen:
            continue
        seen.add(sig)
        results.append(chunk)

    return results


def extractChargeCodeIdModelsFromTimesheetPayload(payload):
    results = []
    for chunk in extractChargeCodeChunksFromTimesheetPayload(payload):
        results.extend(chunk)
    return results


def insertChargeCodesBetweenGroupAndHistory(path, chargeCodeIdModels):
    tmpPath = path + ".tmp"

    def mkChargeCodeLine(groupKey, chunkIndex, chunk):
        obj = {
            "type": "chargeCode",
            "groupKey": groupKey,
            "chunkIndex": chunkIndex,
            "chargeCodes": chunk,
        }
        return json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n"

    chunks = []
    seenNewSignatures = set()
    for chunk in splitChargeCodeModelsIntoChunks(chargeCodeIdModels or []):
        sig = chargeCodeChunkSignature(chunk)
        if sig in seenNewSignatures:
            continue
        seenNewSignatures.add(sig)
        chunks.append(chunk)

    if not chunks:
        return

    existingGroupsByExactSignature: Dict[Tuple[Any, ...], str] = {}
    existingGroupsByCoreSignature: Dict[Tuple[Any, ...], str] = {}

    with open(path, "r", encoding="utf-8") as src:
        rawLines = src.readlines()

    for rawLine in rawLines:
        stripped = rawLine.strip()
        if not stripped:
            continue
        try:
            rec = json.loads(stripped)
        except Exception:
            continue
        if rec.get("type") != "chargeCode":
            continue

        chunk = normalizeChargeCodeChunk(rec.get("chargeCodes") or [])
        if not chunkHasChargeCodeValue(chunk):
            continue

        groupKey = str(rec.get("groupKey") or "")
        if not groupKey:
            continue

        existingGroupsByExactSignature.setdefault(chargeCodeChunkSignature(chunk), groupKey)
        existingGroupsByCoreSignature.setdefault(chargeCodeChunkSignature(chunk, includeServiceItem=False), groupKey)

    newChargeCodeLines: List[str] = []
    for chunkIndex, chunk in enumerate(chunks):
        groupKey = existingGroupsByExactSignature.get(chargeCodeChunkSignature(chunk), "")
        if not groupKey:
            groupKey = existingGroupsByCoreSignature.get(
                chargeCodeChunkSignature(chunk, includeServiceItem=False),
                ""
            )
        newChargeCodeLines.append(mkChargeCodeLine(groupKey, chunkIndex, chunk))

    inserted = False
    with open(tmpPath, "w", encoding="utf-8") as dst:
        for rawLine in rawLines:
            stripped = rawLine.strip()
            if stripped:
                try:
                    rec = json.loads(stripped)
                except Exception:
                    rec = None
                if isinstance(rec, dict):
                    recType = rec.get("type")
                    if recType == "chargeCode":
                        continue
                    if not inserted and recType == "history":
                        for line in newChargeCodeLines:
                            dst.write(line)
                        inserted = True

            dst.write(rawLine)

        if not inserted:
            for line in newChargeCodeLines:
                dst.write(line)

    os.replace(tmpPath, path)


def loadEnv(path="posting.env"):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

_dataDir = os.environ.get("TaskTracker_DATA_DIR", "").strip()
if _dataDir:
    _baseDir = _dataDir
    os.makedirs(_baseDir, exist_ok=True)
else:
    _localAppData = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
    _baseDir = os.path.join(_localAppData, "Task Tracker")
    os.makedirs(_baseDir, exist_ok=True)

_envPath = os.path.join(_baseDir, "posting.env")

try:
    loadEnv(_envPath)
except FileNotFoundError:
    pass
baseUrl = os.getenv("BASE_URL", "").strip()
email = os.getenv("EMAIL", "").strip()
password = os.getenv("PASSWORD", "")
primePath = "/"
loginPath = "/login"
punchesPath = "/punches"

cookieFile = os.path.join(_baseDir, "cookies.txt")


def newSession() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json, text/plain, */*",
    })
    return s


def loadCookies(s: requests.Session) -> bool:
    if not os.path.exists(cookieFile):
        return False
    jar = MozillaCookieJar(cookieFile)
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except Exception:
        return False
    s.cookies = jar
    return True


def saveCookies(s: requests.Session) -> None:
    if not isinstance(s.cookies, MozillaCookieJar):
        jar = MozillaCookieJar(cookieFile)
        for c in s.cookies:
            jar.set_cookie(c)
        s.cookies = jar
    s.cookies.save(ignore_discard=True, ignore_expires=True)


def primeCookies(s: requests.Session) -> None:
    r = s.get(baseUrl + primePath, allow_redirects=True, timeout=30)
    # print("=== PRIME RESPONSE ===")
    # print("status:", r.status_code)
    # print("cookies:", {c.name: c.value for c in s.cookies})
    # print("======================\n")


def getXsrfToken(s):
    for c in s.cookies:
        if c.name.lower() in ("xsrf-token", "xsrf_token"):
            return c.value
    raise RuntimeError("No XSRF token cookie found")


def login(s: requests.Session) -> Tuple[requests.Response, Dict[str, Any]]:
    s.headers.update({
        "Content-Type": "application/json;charset=UTF-8",
        "Origin": baseUrl,
        "Referer": baseUrl + "/",
        "X-Requested-With": "XMLHttpRequest",
    })

    payload = {"email": email, "password": password}
    
    r = s.post(baseUrl + loginPath, json=payload, allow_redirects=False, timeout=30)

    data: Dict[str, Any]
    try:
        data = r.json()
    except Exception as e:
        raise RuntimeError(f"Login did not return JSON: {e}") from e

    # Check for authentication success in response data
    if data.get("authenticated") is False:
        errorMsg = data.get("error", "Unknown authentication error")
        raise RuntimeError(f"Login failed: {errorMsg}")
    
    if not data or data.get("id") is None:
        if isinstance(data, dict) and data.get("error"):
            raise RuntimeError(f"Login error: {data.get('error')}")
        raise RuntimeError("Login failed: No employee ID in response")

    return r, data


def extractEmployeeId(loginJson: Dict[str, Any]) -> str:
    if "id" in loginJson and loginJson["id"]:
        return str(loginJson["id"])

    user = loginJson.get("user")
    if isinstance(user, dict) and user.get("id"):
        return str(user["id"])

    data = loginJson.get("data")
    if isinstance(data, dict) and data.get("id"):
        return str(data["id"])

    raise KeyError(f'Could not find employee id in login JSON. Top-level keys: {list(loginJson.keys())}')


def postPunch(s: requests.Session, punchPayload: Dict[str, Any]) -> requests.Response:
    try:
        s.headers.update({
            "Content-Type": "application/json;charset=UTF-8",
            "Origin": baseUrl,
            "Referer": baseUrl + "/",
            "X-Requested-With": "XMLHttpRequest",
            "X-XSRF-TOKEN": getXsrfToken(s),
        })

        r = s.post(baseUrl + punchesPath, json=punchPayload, timeout=30)
        r.raise_for_status()
        
        punchType = punchPayload.get("type", "PUNCH")
        print(f"✓ {punchType} successful")
        return r
    except Exception as e:
        print(f"✗ Punch failed: {e}")
        raise

def copyPreviousTimesheet(s, dateStr):
    try:
        s.headers.update({
            "Origin": baseUrl,
            "Referer": baseUrl + "/",
            "X-Requested-With": "XMLHttpRequest",
            "X-XSRF-TOKEN": getXsrfToken(s),
        })

        path = f"/timesheet/{dateStr}?copyPreviousTimesheet=true"
        r = s.get(baseUrl + path, timeout=30)
        r.raise_for_status()

        data = r.json()

        timesheetId = data.get("id")
        if not timesheetId:
            raise RuntimeError("timesheet id missing from response")

        chargeCodeIdModels = extractChargeCodeIdModelsFromTimesheetPayload(data)

        return {
            "timesheetId": timesheetId,
            "chargeCodeIDModels": chargeCodeIdModels,
            "raw": data
        }
    except Exception as e:
        print(f"=== COPYtimesheet ERROR ===")
        print(f"Exception: {e}")
        print("=== END COPYIMESHEET ERROR ===")
        raise

def postHoursWorked(s, employeeId, timesheetId, chargeCodeIdModels, dateStr, hours, billable=False, payTypeId=None):
    try:
        s.headers.update({
            "Content-Type": "application/json;charset=UTF-8",
            "Origin": baseUrl,
            "Referer": baseUrl + "/",
            "X-Requested-With": "XMLHttpRequest",
            "X-XSRF-TOKEN": getXsrfToken(s),
        })

        payloadObj = {
            "id": "",
            "date": dateStr,
            "hours": str(hours),
            "chargeCodes": chargeCodeIdModels[:4],
            "employeeId": employeeId,
            "employeeEmail": email,
            "timesheetId": timesheetId,
            "billable": billable,
            "payTypeId": payTypeId,
        }

        r = s.post(baseUrl + "/hoursWorked", json=payloadObj, timeout=30)
        r.raise_for_status()
        
        print(f"✓ Posted {hours}h to timesheet")
        return r
    except Exception as e:
        print(f"✗ Post hours failed: {e}")
        raise

def main() -> int:
    s = newSession()
    #loadCookies(s)

    primeCookies(s)

    loginJson: Optional[Dict[str, Any]] = None
    employeeId: Optional[str] = None

    try:
        _, loginJson = login(s)
        employeeId = extractEmployeeId(loginJson)
    finally:
        saveCookies(s)

    print("employeeId:", employeeId)
    
    today = date.today().isoformat()
    timesheetData = copyPreviousTimesheet(s, today)

    timesheetId = timesheetData["timesheetId"]
    chargeCodeIdModels = timesheetData["chargeCodeIDModels"]

    insertChargeCodesBetweenGroupAndHistory(os.path.join(_baseDir, "tasks.jsonl"), chargeCodeIdModels)
    #postHoursWorked(s, employeeId, timesheetId, chargeCodeIdModels)

##    print(timesheetId, chargeCodeIdModels)

    punchPayload: Dict[str, Any] = {
        "id": "",
        "punchDate": "01/12/2026 05:00 pm",
        "type": "OUT",
        "employeeId": employeeId,
        "revisionNumber": -1,
        "chargeCodes": [],
        "payType": None,
        "noteModel": None,
        "billable": False,
        "date": None,
        "timesheetPage": True,
        "location": None,
        "new": True
    }

    # postPunch(s, punchPayload)
    saveCookies(s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
