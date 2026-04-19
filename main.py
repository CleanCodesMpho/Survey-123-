from fastapi import FastAPI, Request
from arcgis.gis import GIS
from arcgis.features import FeatureLayer
import os
import qrcode
from datetime import datetime

from docxtpl import DocxTemplate, InlineImage
from docx.shared import Mm

# =========================
# APP INIT
# =========================
app = FastAPI()

# =========================
# AGOL AUTH
# =========================
AGOL_USERNAME = os.getenv("AGOL_USERNAME")
AGOL_PASSWORD = os.getenv("AGOL_PASSWORD")

if not AGOL_USERNAME or not AGOL_PASSWORD:
    raise Exception("AGOL credentials not set in environment variables")

gis = GIS("https://www.arcgis.com", AGOL_USERNAME, AGOL_PASSWORD)

# =========================
# FEATURE LAYER
# =========================
SURVEY_LAYER_URL = "https://services9.arcgis.com/yF9lC2Enj2rx9gHK/arcgis/rest/services/service_eec5deb1b491460281f8492dcd8a631a/FeatureServer/0"
layer = FeatureLayer(SURVEY_LAYER_URL, gis=gis)

# =========================
# TEMPLATE
# =========================
TEMPLATE_PATH = "template.docx"

if not os.path.exists(TEMPLATE_PATH):
    raise Exception("template.docx not found in project root")

# =========================
# HEALTH CHECK
# =========================
@app.get("/")
def home():
    return {"status": "running"}

# =========================
# DEBUG ENDPOINT
# =========================
@app.get("/debug")
def debug():
    return {
        "template_exists": os.path.exists(TEMPLATE_PATH),
        "username_set": bool(AGOL_USERNAME),
        "password_set": bool(AGOL_PASSWORD),
        "layer_url": SURVEY_LAYER_URL
    }

# =========================
# TEST QUERY
# =========================
@app.get("/test-query/{objectid}")
def test_query(objectid: int):
    result = layer.query(where=f"OBJECTID={objectid}", out_fields="*")
    return {
        "found": len(result.features),
        "attributes": result.features[0].attributes if result.features else None
    }

# =========================
# TEST UPDATE
# =========================
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

# =========================
# QR GENERATOR
# =========================
def generate_qr(url, path):
    img = qrcode.make(url)
    img.save(path)

# =========================
# REPORT GENERATION
# =========================
def generate_report(attributes):
    objectid = attributes.get("OBJECTID")

    os.makedirs("output", exist_ok=True)

    docx_file = os.path.join("output", f"report_{objectid}.docx")
    qr_file = os.path.join("output", f"qr_{objectid}.png")

    # Placeholder for now
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

# =========================
# UPDATE FEATURE
# =========================
def update_feature(objectid, url, status):
    result = layer.edit_features(updates=[{
        "attributes": {
            "OBJECTID": objectid,
            "report_url": url,
            "report_status": status
        }
    }])
    return result

# =========================
# WEBHOOK ENDPOINT
# =========================
@app.post("/webhook/survey123")
async def survey_webhook(request: Request):
    payload = await request.json()
    objectid = None

    try:
        # STEP 1: extract OBJECTID from Survey123 payload
        if "submittedRecord" in payload:
            objectid = payload["submittedRecord"]["attributes"]["OBJECTID"]
        elif "serverResponse" in payload:
            objectid = payload["serverResponse"]["objectId"]
        else:
            return {
                "status": "failed",
                "error": "OBJECTID not found in payload",
                "payload_keys": list(payload.keys())
            }

        # STEP 2: mark webhook received
        update_feature(objectid, "webhook_received", "received")

        # STEP 3: query feature
        result = layer.query(where=f"OBJECTID={objectid}", out_fields="*")

        if not result.features:
            update_feature(objectid, "query_failed", "failed")
            return {
                "status": "failed",
                "error": f"No feature found for OBJECTID {objectid}"
            }

        attributes = result.features[0].attributes

        # STEP 4: mark query success
        update_feature(objectid, "query_ok", "queried")

        # STEP 5: generate report
        report_url = generate_report(attributes)

        # STEP 6: mark final success
        edit_result = update_feature(objectid, report_url, "completed")

        return {
            "status": "success",
            "objectid": objectid,
            "report_url": report_url,
            "edit_result": str(edit_result)
        }

    except Exception as e:
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
