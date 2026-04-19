from fastapi import FastAPI, Request
from arcgis.gis import GIS
from arcgis.features import FeatureLayer
import os
import qrcode
from datetime import datetime

from docxtpl import DocxTemplate, InlineImage
from docx.shared import Mm

app = FastAPI()

AGOL_USERNAME = os.getenv("AGOL_USERNAME")
AGOL_PASSWORD = os.getenv("AGOL_PASSWORD")

if not AGOL_USERNAME or not AGOL_PASSWORD:
    raise Exception("AGOL credentials not set in environment variables")

gis = GIS("https://www.arcgis.com", AGOL_USERNAME, AGOL_PASSWORD)

SURVEY_LAYER_URL = "https://services9.arcgis.com/yF9lC2Enj2rx9gHK/arcgis/rest/services/service_eec5deb1b491460281f8492dcd8a631a/FeatureServer/0"
layer = FeatureLayer(SURVEY_LAYER_URL, gis=gis)

TEMPLATE_PATH = "CHEMICAL SAFETY Report"

if not os.path.exists(TEMPLATE_PATH):
    raise Exception("template.docx not found in project root")

LAST_PAYLOAD = {}
LAST_ERROR = None

@app.get("/")
def home():
    return {"status": "running"}

@app.get("/debug")
def debug():
    return {
        "template_exists": os.path.exists(TEMPLATE_PATH),
        "username_set": bool(AGOL_USERNAME),
        "password_set": bool(AGOL_PASSWORD),
        "layer_url": SURVEY_LAYER_URL
    }

@app.get("/last-payload")
def last_payload():
    return {
        "last_error": LAST_ERROR,
        "payload": LAST_PAYLOAD
    }

@app.get("/test-query/{objectid}")
def test_query(objectid: int):
    result = layer.query(where=f"OBJECTID={objectid}", out_fields="*")
    return {
        "found": len(result.features),
        "attributes": result.features[0].attributes if result.features else None
    }

@app.get("/test-update/{objectid}")
def test_update(objectid: int):
    result = layer.edit_features(updates=[{
        "attributes": {
            "OBJECTID": objectid,
            "report_status": "test_ok",
            "report_url": "https://example.com/test.docx"
        }
    }])
    return {"edit_result": result}

def extract_objectid(payload):
    if "submittedRecord" in payload:
        attrs = payload["submittedRecord"].get("attributes", {})
        if "OBJECTID" in attrs:
            return attrs["OBJECTID"]

    if "serverResponse" in payload:
        sr = payload["serverResponse"]
        if isinstance(sr, dict):
            if "objectId" in sr:
                return sr["objectId"]
            if "editResults" in sr and sr["editResults"]:
                first = sr["editResults"][0]
                if "objectId" in first:
                    return first["objectId"]

    if "feature" in payload:
        feature = payload["feature"]
        if isinstance(feature, dict):
            attrs = feature.get("attributes", {})
            if "OBJECTID" in attrs:
                return attrs["OBJECTID"]
            result = feature.get("result", {})
            if "objectId" in result:
                return result["objectId"]

    if "features" in payload and payload["features"]:
        first = payload["features"][0]
        attrs = first.get("attributes", {})
        if "OBJECTID" in attrs:
            return attrs["OBJECTID"]

    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in ("OBJECTID", "objectId"):
                return value
            found = extract_objectid(value)
            if found is not None:
                return found

    if isinstance(payload, list):
        for item in payload:
            found = extract_objectid(item)
            if found is not None:
                return found

    return None

def generate_qr(url, path):
    img = qrcode.make(url)
    img.save(path)

def generate_report(attributes):
    objectid = attributes.get("OBJECTID")

    os.makedirs("output", exist_ok=True)

    docx_file = os.path.join("output", f"report_{objectid}.docx")
    qr_file = os.path.join("output", f"qr_{objectid}.png")

    report_url = f"https://your-storage/reports/report_{objectid}.pdf"

    generate_qr(report_url, qr_file)

    edit_date = attributes.get("EditDate")
    if edit_date:
        edit_date = datetime.fromtimestamp(edit_date / 1000).strftime("%Y-%m-%d %H:%M:%S")
    else:
        edit_date = "N/A"

    doc = DocxTemplate(TEMPLATE_PATH)
    qr_image = InlineImage(doc, qr_file, width=Mm(25))

    context = {
        "objectid": objectid,
        "name": attributes.get("owner_name", "N/A"),
        "location": attributes.get("Location", "N/A"),
        "date": edit_date,
        "qr_code": qr_image
    }

    doc.render(context)
    doc.save(docx_file)

    return report_url

def update_feature(objectid, url, status):
    result = layer.edit_features(updates=[{
        "attributes": {
            "OBJECTID": objectid,
            "report_url": url,
            "report_status": status
        }
    }])
    return result

@app.post("/webhook/survey123")
async def survey_webhook(request: Request):
    global LAST_PAYLOAD, LAST_ERROR

    payload = await request.json()
    LAST_PAYLOAD = payload
    LAST_ERROR = None
    objectid = None

    try:
        objectid = extract_objectid(payload)

        if objectid is None:
            LAST_ERROR = f"OBJECTID not found. Payload keys: {list(payload.keys()) if isinstance(payload, dict) else 'not a dict'}"
            return {
                "status": "failed",
                "error": LAST_ERROR
            }

        update_feature(objectid, "webhook_received", "received")

        result = layer.query(where=f"OBJECTID={objectid}", out_fields="*")
        if not result.features:
            update_feature(objectid, "query_failed", "failed")
            LAST_ERROR = f"No feature found for OBJECTID {objectid}"
            return {
                "status": "failed",
                "error": LAST_ERROR
            }

        attributes = result.features[0].attributes
        update_feature(objectid, "query_ok", "queried")

        report_url = generate_report(attributes)

        edit_result = update_feature(objectid, report_url, "completed")

        return {
            "status": "success",
            "objectid": objectid,
            "report_url": report_url,
            "edit_result": str(edit_result)
        }

    except Exception as e:
        LAST_ERROR = str(e)
        if objectid is not None:
            try:
                update_feature(objectid, f"ERROR: {str(e)}", "failed")
            except Exception:
                pass

        return {
            "status": "failed",
            "objectid": objectid,
            "error": str(e)
        }
