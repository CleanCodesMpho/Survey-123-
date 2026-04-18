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
# AGOL AUTH (RENDER SAFE)
# =========================
gis = GIS(
    "https://www.arcgis.com",
    os.getenv("AGOL_USERNAME"),
    os.getenv("AGOL_PASSWORD")
)

# =========================
# FEATURE LAYER
# =========================
SURVEY_LAYER_URL = "https://services9.arcgis.com/yF9lC2Enj2rx9gHK/arcgis/rest/services/service_eec5deb1b491460281f8492dcd8a631a/FeatureServer/0"
layer = FeatureLayer(SURVEY_LAYER_URL)

# =========================
# TEMPLATE
# =========================
TEMPLATE_PATH = "template.docx"

# =========================
# HEALTH CHECK (RENDER REQUIRED)
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

    report_url = f"https://your-storage/reports/report_{objectid}.pdf"

    # Generate QR
    generate_qr(report_url, qr_file)

    # Load template
    doc = DocxTemplate(TEMPLATE_PATH)

    qr_image = InlineImage(doc, qr_file, width=Mm(25))

    context = {
        "objectid": objectid,
        "name": attributes.get("owner_name", "N/A"),
        "location": attributes.get("Location", "N/A"),
        "date": attributes.get("EditDate", "N/A"),
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

    print("Webhook received:", payload)  # DEBUG LOG

    try:
        # SAFE OBJECTID EXTRACTION (handles Survey123 variations)
        objectid = None

        if "feature" in payload:
            objectid = payload["feature"]["attributes"].get("OBJECTID")

        elif "features" in payload:
            objectid = payload["features"][0]["attributes"].get("OBJECTID")

        if not objectid:
            return {"status": "failed", "error": "OBJECTID not found in payload"}

        # FETCH FULL FEATURE FROM AGOL
        feature = layer.query(
            where=f"OBJECTID={objectid}",
            out_fields="*"
        ).features[0]

        attributes = feature.attributes

        # GENERATE REPORT
        report_url = generate_report(attributes)

        # UPDATE FEATURE LAYER
        update_feature(objectid, report_url, "completed")

        return {
            "status": "success",
            "objectid": objectid,
            "report_url": report_url
        }

    except Exception as e:

        print("ERROR:", str(e))

        return {
            "status": "failed",
            "error": str(e)
        }
