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
# AGOL AUTH (SAFE)
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
layer = FeatureLayer(SURVEY_LAYER_URL)

# =========================
# TEMPLATE
# =========================
TEMPLATE_PATH = "template.docx"

if not os.path.exists(TEMPLATE_PATH):
    raise Exception("template.docx not found in project root")

# =========================
# HEALTH CHECK (RENDER)
# =========================
@app.get("/")
def home():
    return {"status": "running"}

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

    # ⚠️ Placeholder (we will fix later with real storage)
    report_url = f"https://your-storage/reports/report_{objectid}.pdf"

    # Generate QR
    generate_qr(report_url, qr_file)

    # Convert date properly
    edit_date = attributes.get("EditDate")
    if edit_date:
        edit_date = datetime.fromtimestamp(edit_date / 1000).strftime("%Y-%m-%d %H:%M:%S")
    else:
        edit_date = "N/A"

    # Load template
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
# UPDATE FEATURE LAYER
# =========================
def update_feature(objectid, url, status):

    layer.edit_features(updates=[{
        "attributes": {
            "OBJECTID": objectid,
            "report_url": url,
            "report_status": status,
            "last_updated": datetime.now().isoformat()
        }
    }])

# =========================
# WEBHOOK ENDPOINT
# =========================
@app.post("/webhook/survey123")
async def survey_webhook(request: Request):

    payload = await request.json()
    objectid = None

    try:
        # Handle Survey123 payload formats
        if "submittedRecord" in payload:
            objectid = payload["submittedRecord"]["attributes"]["OBJECTID"]

        elif "serverResponse" in payload:
            objectid = payload["serverResponse"]["objectId"]

        else:
            return {"status": "failed", "error": "OBJECTID not found in payload"}

        print(f"Processing OBJECTID: {objectid}")

        # Query feature safely
        result = layer.query(
            where=f"OBJECTID={objectid}",
            out_fields="*"
        )

        if not result.features:
            raise Exception(f"No feature found for OBJECTID {objectid}")

        attributes = result.features[0].attributes

        # Generate report
        report_url = generate_report(attributes)

        # Update feature layer
        update_feature(objectid, report_url, "completed")

        print(f"Completed OBJECTID: {objectid}")

        return {
            "status": "success",
            "objectid": objectid,
            "report_url": report_url
        }

    except Exception as e:
        print(f"FAILED OBJECTID {objectid}: {str(e)}")
        return {"status": "failed", "error": str(e)}
