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
TEMPLATE_PATH = "CHEMICAL SAFETY Report.docx"

if not os.path.exists(TEMPLATE_PATH):
    raise Exception(f"{TEMPLATE_PATH} not found in project root")

# =========================
# TEMP PAYLOAD STORAGE
# =========================
LAST_PAYLOAD = {}
LAST_ERROR = None

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
# LAST PAYLOAD
# =========================
@app.get("/last-payload")
def last_payload():
    return {
        "last_error": LAST_ERROR,
        "payload": LAST_PAYLOAD
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
# HELPER: EXTRACT OBJECTID
# =========================
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

# =========================
# QR GENERATOR
# =========================
def generate_qr(url, path):
    img = qrcode.make(url)
    img.save(path)

# =========================
# UPLOAD REPORT TO AGOL
# =========================
def upload_report_to_agol(file_path, objectid):
    root_folder = gis.content.folders.get()

    item_properties = {
        "title": f"Report_{objectid}",
        "type": "Microsoft Word",
        "tags": ["survey123", "report", "automation"],
        "snippet": f"Automatically generated report for Survey123 submission {objectid}"
    }

    report_item = root_folder.add(
        item_properties=item_properties,
        file=file_path
    ).result()

    report_item.sharing.sharing_level = "EVERYONE"

    return f"https://www.arcgis.com/home/item.html?id={report_item.itemid}"

# =========================
# REPORT GENERATION
# =========================
def generate_report(attributes, objectid):
    os.makedirs("output", exist_ok=True)

    docx_file = os.path.join("output", f"report_{objectid}.docx")
    qr_file = os.path.join("output", f"qr_{objectid}.png")

    # Temporary QR target for first render
    temp_url = f"https://www.arcgis.com/home/item.html?id=temp-{objectid}"
    generate_qr(temp_url, qr_file)

    edit_date = attributes.get("EditDate")
    if edit_date:
        edit_date = datetime.fromtimestamp(edit_date / 1000).strftime("%Y-%m-%d %H:%M:%S")
    else:
        edit_date = "N/A"

    doc = DocxTemplate(TEMPLATE_PATH)
    qr_image = InlineImage(doc, qr_file, width=Mm(25))

    context = {
        "municipality": attributes.get("municipality", "N/A"),
        "premise_name": attributes.get("premise_name", "N/A"),
        "address": attributes.get("address", "N/A"),
        "Premise_Type": attributes.get("Premise_Type", "N/A"),
        "owner_name": attributes.get("owner_name", "N/A"),
        "contact": attributes.get("contact", "N/A"),
        "inspection_date": edit_date,
        "EHP": attributes.get("EHP", "N/A"),

        "Q1": attributes.get("Q1", "N/A"),
        "Rem1": attributes.get("Rem1", "N/A"),
        "Q2": attributes.get("Q2", "N/A"),
        "Rem2": attributes.get("Rem2", "N/A"),
        "Q3": attributes.get("Q3", "N/A"),
        "Rem3": attributes.get("Rem3", "N/A"),
        "Q4": attributes.get("Q4", "N/A"),
        "Rem4": attributes.get("Rem4", "N/A"),
        "Q5": attributes.get("Q5", "N/A"),
        "Rem5": attributes.get("Rem5", "N/A"),

        "Q6": attributes.get("Q6", "N/A"),
        "Rem6": attributes.get("Rem6", "N/A"),
        "Q7": attributes.get("Q7", "N/A"),
        "Rem7": attributes.get("Rem7", "N/A"),
        "Q8": attributes.get("Q8", "N/A"),
        "Rem8": attributes.get("Rem8", "N/A"),
        "Q9": attributes.get("Q9", "N/A"),
        "Rem9": attributes.get("Rem9", "N/A"),
        "Q10": attributes.get("Q10", "N/A"),
        "Rem10": attributes.get("Rem10", "N/A"),

        "Q11": attributes.get("Q11", "N/A"),
        "Rem11": attributes.get("Rem11", "N/A"),
        "Q12": attributes.get("Q12", "N/A"),
        "Rem12": attributes.get("Rem12", "N/A"),
        "Q13": attributes.get("Q13", "N/A"),
        "Rem13": attributes.get("Rem13", "N/A"),
        "Q14": attributes.get("Q14", "N/A"),
        "Rem14": attributes.get("Rem14", "N/A"),
        "Q15": attributes.get("Q15", "N/A"),
        "Rem15": attributes.get("Rem15", "N/A"),

        "Q16": attributes.get("Q16", "N/A"),
        "Rem16": attributes.get("Rem16", "N/A"),
        "Q17": attributes.get("Q17", "N/A"),
        "Rem17": attributes.get("Rem17", "N/A"),
        "Q18": attributes.get("Q18", "N/A"),
        "Rem18": attributes.get("Rem18", "N/A"),
        "Q19": attributes.get("Q19", "N/A"),
        "Rem19": attributes.get("Rem19", "N/A"),

        "Q20": attributes.get("Q20", "N/A"),
        "Rem20": attributes.get("Rem20", "N/A"),
        "Q21": attributes.get("Q21", "N/A"),
        "Rem21": attributes.get("Rem21", "N/A"),
        "Q22": attributes.get("Q22", "N/A"),
        "Rem22": attributes.get("Rem22", "N/A"),
        "Q23": attributes.get("Q23", "N/A"),
        "Rem23": attributes.get("Rem23", "N/A"),

        "Q24": attributes.get("Q24", "N/A"),
        "Rem24": attributes.get("Rem24", "N/A"),
        "Q25": attributes.get("Q25", "N/A"),
        "Rem25": attributes.get("Rem25", "N/A"),
        "Q26": attributes.get("Q26", "N/A"),
        "Rem26": attributes.get("Rem26", "N/A"),
        "Q27": attributes.get("Q27", "N/A"),
        "Rem27": attributes.get("Rem27", "N/A"),

        "Q28": attributes.get("Q28", "N/A"),
        "Rem28": attributes.get("Rem28", "N/A"),
        "Q29": attributes.get("Q29", "N/A"),
        "Rem29": attributes.get("Rem29", "N/A"),
        "Q30": attributes.get("Q30", "N/A"),
        "Rem30": attributes.get("Rem30", "N/A"),
        "Q31": attributes.get("Q31", "N/A"),
        "Rem31": attributes.get("Rem31", "N/A"),

        "Q32": attributes.get("Q32", "N/A"),
        "Rem32": attributes.get("Rem32", "N/A"),
        "Q33": attributes.get("Q33", "N/A"),
        "Rem33": attributes.get("Rem33", "N/A"),
        "Q34": attributes.get("Q34", "N/A"),
        "Rem34": attributes.get("Rem34", "N/A"),
        "Q35": attributes.get("Q35", "N/A"),
        "Rem35": attributes.get("Rem35", "N/A"),

        "Q36": attributes.get("Q36", "N/A"),
        "Rem36": attributes.get("Rem36", "N/A"),
        "Q37": attributes.get("Q37", "N/A"),
        "Rem37": attributes.get("Rem37", "N/A"),
        "Q38": attributes.get("Q38", "N/A"),
        "Rem38": attributes.get("Rem38", "N/A"),
        "Q39": attributes.get("Q39", "N/A"),
        "Rem39": attributes.get("Rem39", "N/A"),

        "Q40": attributes.get("Q40", "N/A"),
        "Rem40": attributes.get("Rem40", "N/A"),
        "Q41": attributes.get("Q41", "N/A"),
        "Rem41": attributes.get("Rem41", "N/A"),
        "Q42": attributes.get("Q42", "N/A"),
        "Rem42": attributes.get("Rem42", "N/A"),
        "Q43": attributes.get("Q43", "N/A"),
        "Rem43": attributes.get("Rem43", "N/A"),

        "Q44": attributes.get("Q44", "N/A"),
        "Rem44": attributes.get("Rem44", "N/A"),
        "Q45": attributes.get("Q45", "N/A"),
        "Rem45": attributes.get("Rem45", "N/A"),
        "Q46": attributes.get("Q46", "N/A"),
        "Rem46": attributes.get("Rem46", "N/A"),
        "Q47": attributes.get("Q47", "N/A"),
        "Rem47": attributes.get("Rem47", "N/A"),

        "Non_compliances": attributes.get("Non_compliances", "N/A"),
        "Corrective_action": attributes.get("Corrective_action", "N/A"),
        "Overall_compliance_status": attributes.get("Overall_compliance_status", "N/A"),
        "ehp_signature": attributes.get("ehp_signature", "N/A"),
        "HI_number": attributes.get("HI_number", "N/A"),
        "Owner_Manager_signatures": attributes.get("Owner_Manager_signatures", "N/A"),

        "qr_code": qr_image
    }

    doc.render(context)
    doc.save(docx_file)

    real_url = upload_report_to_agol(docx_file, objectid)
    return real_url

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

        report_url = generate_report(attributes, objectid)

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
