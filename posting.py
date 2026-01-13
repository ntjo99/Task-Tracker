import os
from http.cookiejar import MozillaCookieJar
from typing import Any, Dict, Optional, Tuple
from datetime import date, datetime
import requests
import json

def insertChargeCodesBetweenGroupAndHistory(path, chargeCodeIdModels):
    tmpPath = path + ".tmp"

    def chunk4(arr):
        for i in range(0, len(arr), 4):
            yield i // 4, arr[i:i+4]

    def chunkSignature(chunk):
        ids = []
        for x in chunk:
            if isinstance(x, dict):
                ids.append(x.get("chargeCodeId"))
            else:
                ids.append(None)
        while len(ids) < 4:
            ids.append(None)
        return tuple(ids[:4])

    def existingSignatureFromChargeCodeRecord(rec):
        chunk = rec.get("chargeCodes")
        if not isinstance(chunk, list):
            return None
        return chunkSignature(chunk)

    def mkChargeCodeLine(groupKey, chunkIndex, chunk):
        obj = {
            "type": "chargeCode",
            "groupKey": groupKey,
            "chunkIndex": chunkIndex,
            "chargeCodes": chunk,
        }
        return json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n"

    with open(path, "r", encoding="utf-8") as src, open(tmpPath, "w", encoding="utf-8") as dst:
        inGroup = False
        groupKey = ""
        seenChargeCodeSigs = set()
        insertedSigs = set()

        def insertMissingChargeCodes():
            nonlocal insertedSigs
            for idx, chunk in chunk4(chargeCodeIdModels):
                sig = chunkSignature(chunk)
                if sig in seenChargeCodeSigs or sig in insertedSigs:
                    continue
                dst.write(mkChargeCodeLine(groupKey, idx, chunk))
                insertedSigs.add(sig)

        for rawLine in src:
            stripped = rawLine.strip()
            if not stripped:
                dst.write(rawLine)
                continue

            try:
                rec = json.loads(stripped)
            except Exception:
                dst.write(rawLine)
                continue

            recType = rec.get("type")

            if recType == "group":
                dst.write(rawLine)  # verbatim
                inGroup = True
                insertedSigs = set()
                seenChargeCodeSigs = set()
                groupKey = rec.get("groupKey") or rec.get("key") or ""
                continue

            if inGroup and recType == "chargeCode":
                sig = existingSignatureFromChargeCodeRecord(rec)
                if sig is not None:
                    seenChargeCodeSigs.add(sig)
                dst.write(rawLine)  # verbatim
                continue

            if inGroup and recType == "history":
                insertMissingChargeCodes()
                inGroup = False
                dst.write(rawLine)  # verbatim
                continue

            dst.write(rawLine)

        # If file ends while still "inGroup" (no history encountered), do nothing.
        # This preserves your file unchanged unless we hit the group->history boundary.

    os.replace(tmpPath, path)

def loadEnv(path="posting.env"):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

loadEnv()
baseUrl = os.environ["BASE_URL"]
email = os.environ["EMAIL"]
password = os.environ["PASSWORD"]
primePath = "/"
loginPath = "/login"
punchesPath = "/punches"

cookieFile = "cookies.txt"


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

    # print("=== LOGIN RESPONSE ===")
    # print("status:", r.status_code)
    if (r.status_code == 200):
        print("Login Success")

    # print("\n-- headers --")
    # for k, v in r.headers.items():
    #     print(f"{k}: {v}")

    # print("\n-- body --")
    # print(r.text)

    # print("\n-- cookies after login --")
    # for c in s.cookies:
    #     print(f"{c.name}={c.value}; domain={c.domain}; path={c.path}")

    # print("=======================")

    r.raise_for_status()

    data: Dict[str, Any]
    try:
        data = r.json()
    except Exception as e:
        raise RuntimeError(f"Login did not return JSON: {e}") from e

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

        chargeCodeIdModels = []

        hoursWorked = data.get("hoursWorked", [])
        for entry in hoursWorked:
            models = entry.get("chargeCodeIDModels", [])
            for m in models:
                chargeCodeIdModels.append(m)

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

    insertChargeCodesBetweenGroupAndHistory("tasks.jsonl", chargeCodeIdModels)

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
