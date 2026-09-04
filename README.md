# تایپ گفتاری فارسی

وب‌اپلیکیشن محلی برای تبدیل گفتار فارسی به متن. مدل‌ها را با دکمه رادیویی عوض کنید تا ببینید کدام بهتر تایپ می‌کند.

## مدل‌های پشتیبانی‌شده

برنامه پوشه‌های داخل `models` را می‌خواند (یا مسیر `C:\Users\omid\Documents\appointment\models`):

| پوشه | موتور | دکمه رادیویی |
|------|--------|----------------|
| `vosk-model-fa` | Vosk | بله — تشخیص زنده |
| `whisper-persian-v4-ct2` | Faster-Whisper (CTranslate2) | بله |
| `shenava-koochik-ctc` | sherpa-onnx CTC | بله |
| `shenava-koochik-v1.5` | sherpa-onnx RNNT یا فایل `.nemo` | بله |
| `piper-voice-fa` | Piper TTS | نمایش داده می‌شود ولی غیرفعال است (تبدیل متن به گفتار است، نه تایپ) |

## اجرا در ویندوز

```bat
run.bat
```

یا دستی:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:MODELS_DIR = "C:\Users\omid\Documents\appointment\models"
.\.venv\Scripts\python.exe -m app
```

سپس مرورگر را روی [http://127.0.0.1:8000](http://127.0.0.1:8000) باز کنید.

اگر مدل‌ها جای دیگری هستند، `config.example.json` را به `config.json` کپی کنید و مسیر را بگذارید.

## استفاده

1. یک مدل را با دکمه رادیویی انتخاب کنید. همان لحظه مدل در حافظه بارگذاری می‌شود.
2. **شروع** را بزنید و فارسی صحبت کنید.
3. **توقف** را بزنید تا متن نهایی نوشته شود.
4. مدل دیگری را انتخاب کنید. اگر همان صدای قبلی هنوز موجود باشد، دوباره با مدل جدید رونویسی می‌شود تا مقایسه کنید.
5. نتیجه هر مدل در ستون «مقایسه مدل‌ها» می‌ماند.

می‌توانید به‌جای میکروفون یک فایل WAV هم بارگذاری کنید.

## وابستگی اختیاری NeMo

اگر `shenava-koochik-v1.5` فقط فایل `.nemo` دارد:

```powershell
py -m pip install "nemo_toolkit[asr]"
```

اگر همان پوشه `encoder.onnx` / `decoder.onnx` / `joiner.onnx` و `tokens.txt` داشته باشد، برنامه از sherpa-onnx استفاده می‌کند و به NeMo نیاز نیست.

## تست

```powershell
py -m unittest discover -s tests -v
```
