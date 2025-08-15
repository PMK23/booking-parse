# main.py
import os
import json
import zipfile
from fastapi import FastAPI, Request, Form, Response
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from threading import Thread
from parser import BookingParser

# Настройки
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

HOTELS_CSV = os.path.join(OUTPUT_DIR, "hotels.csv")
CONFIG_FILE = "config.json"

app = FastAPI(title="Booking Parser")
templates = Jinja2Templates(directory="templates")


def load_hotels():
    if not os.path.exists(HOTELS_CSV):
        return []
    try:
        import pandas as pd
        df = pd.read_csv(HOTELS_CSV, encoding='utf-8')
        if "Hotel Name" not in df.columns or "Booking URL" not in df.columns:
            return []
        return df.to_dict('records')
    except Exception as e:
        print(f"Ошибка загрузки отелей: {e}")
        return []


def get_txt_files():
    files = []
    for f in os.listdir(OUTPUT_DIR):
        if f.endswith(".txt"):
            path = os.path.join(OUTPUT_DIR, f)
            mtime = os.path.getmtime(path)
            files.append({"name": f, "path": path, "mtime": mtime})
    return sorted(files, key=lambda x: x["mtime"], reverse=True)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    hotels = load_hotels()
    files = get_txt_files()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "hotels": hotels,
        "files": files
    })


@app.post("/parse", response_class=HTMLResponse)
async def parse(request: Request, url: str = Form(None)):
    final_url = (url or "").strip()
    if not final_url:
        hotels = load_hotels()
        files = get_txt_files()
        return templates.TemplateResponse("index.html", {
            "request": request,
            "error": "Введите ссылку или выберите отель.",
            "hotels": hotels,
            "files": files
        })

    # Запускаем парсинг в фоне
    def run_parsing():
        parser = BookingParser()
        parser.parse_reviews(final_url, OUTPUT_DIR)  # без progress_callback

    thread = Thread(target=run_parsing, daemon=True)
    thread.start()

    # Возвращаем страницу с сообщением
    hotels = load_hotels()
    files = get_txt_files()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "hotels": hotels,
        "files": files,
        "message": "Парсинг запущен. Обновите страницу (через минуту), чтобы увидеть результаты."
    })


@app.get("/download-all")
async def download_all():
    files = [f for f in os.listdir(OUTPUT_DIR) if f.endswith(".txt")]
    if not files:
        return {"error": "Нет файлов для скачивания"}

    zip_path = os.path.join(OUTPUT_DIR, "all_reviews.zip")
    with zipfile.ZipFile(zip_path, 'w') as zf:
        for file in files:
            file_path = os.path.join(OUTPUT_DIR, file)
            zf.write(file_path, arcname=file)

    return FileResponse(
        path=zip_path,
        filename="all_reviews.zip",
        media_type="application/zip"
    )


@app.get("/files/{filename}")
async def read_file(filename: str):
    file_path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(file_path) or not filename.endswith(".txt"):
        return {"error": "Файл не найден"}
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    return Response(content, media_type="text/plain; charset=utf-8")


@app.get("/download/{filename}")
async def download_file(filename: str):
    file_path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(file_path) or not filename.endswith(".txt"):
        return JSONResponse({"error": "Файл не найден"}, status_code=404)
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="text/plain"
    )

@app.post("/delete/{filename}")
async def delete_file(filename: str):
    file_path = os.path.join(OUTPUT_DIR, filename)
    try:
        if os.path.exists(file_path) and filename.endswith(".txt"):
            os.remove(file_path)
            return JSONResponse({"success": True, "message": f"Файл {filename} удалён"})
        else:
            return JSONResponse({"success": False, "error": "Файл не найден"}, status_code=404)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

@app.post("/delete_hotel")
async def delete_hotel(url: str = Form(...)):
    if not url or not url.startswith("http"):
        return JSONResponse({"success": False, "error": "Некорректный URL"})

    if not os.path.exists(HOTELS_CSV):
        return JSONResponse({"success": False, "error": "Файл отелей не найден"})

    try:
        import pandas as pd
        df = pd.read_csv(HOTELS_CSV, encoding='utf-8')
        if "Booking URL" not in df.columns:
            return JSONResponse({"success": False, "error": "Некорректный формат файла"})

        filtered = df[df["Booking URL"] != url]
        if len(filtered) == len(df):
            return JSONResponse({"success": False, "error": "Отель не найден"})

        filtered.to_csv(HOTELS_CSV, index=False, encoding='utf-8')
        return JSONResponse({"success": True, "message": "Отель удалён"})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.post("/add_hotel")
async def add_hotel(name: str = Form(...), url: str = Form(...)):
    name = name.strip()
    url = url.strip()

    if not name or not url:
        return {"success": False, "error": "Заполните все поля"}

    if not url.startswith(("http://", "https://")):
        return {"success": False, "error": "Ссылка должна начинаться с http:// или https://"}

    if "#tab-reviews" not in url:
        url = url.split("#")[0] + "#tab-reviews"

    if os.path.exists(HOTELS_CSV):
        try:
            import pandas as pd
            df = pd.read_csv(HOTELS_CSV, encoding='utf-8')
            if (df["Booking URL"] == url).any():
                return {"success": False, "error": "Этот URL уже добавлен"}
        except:
            df = pd.DataFrame(columns=["Hotel Name", "Booking URL"])
    else:
        df = pd.DataFrame(columns=["Hotel Name", "Booking URL"])

    new_row = pd.DataFrame([{"Hotel Name": name, "Booking URL": url}])
    df = pd.concat([df, new_row], ignore_index=True)
    df.to_csv(HOTELS_CSV, index=False, encoding='utf-8')

    return {"success": True, "name": name, "url": url}