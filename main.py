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

TEMPLATE_PATH = "template.docx"

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

def update_feature(objectid, url=None, status="completed"):
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
    payload = await request.json()
    objectid = None

    try:
        if "submittedRecord" in payload:
            objectid = payload["submittedRecord"]["attributes"]["OBJECTID"]
        elif "serverResponse" in payload:
            objectid = payload["serverResponse"]["objectId"]
        else:
            return {"status": "failed", "error": "OBJECTID not found in payload"}

        result = layer.query(where=f"OBJECTID={objectid}", out_fields="*")

        if not result.features:
            update_feature(objectid, None, "failed")
            return {"status": "failed", "error": f"No feature found for OBJECTID {objectid}"}

        attributes = result.features[0].attributes

        report_url = generate_report(attributes)

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
                update_feature(objectid, None, "failed")
            except Exception:
                pass

        return {
            "status": "failed",
            "objectid": objectid,
            "error": str(e)
        }
