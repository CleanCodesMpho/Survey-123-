from fastapi import FastAPI, Request

app = FastAPI()

@app.post("/webhook/survey123")
async def webhook(request: Request):
    data = await request.json()
    return {"status": "received", "payload": data}
