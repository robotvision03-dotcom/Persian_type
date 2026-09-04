# تایپ گفتاری فارسی

وب‌اپلیکیشن محلی: گفتار فارسی با **شنوا کوچیک CTC** به متن تبدیل می‌شود، بعد همان متن برای آزمایش سرعت و دقت به مدل‌های Ollama فرستاده می‌شود.

تشخیص گفتار فقط از `shenava-koochik-ctc` (sherpa-onnx CTC) استفاده می‌کند. دکمه رادیویی ندارد.

## اجرا در ویندوز

Ollama باید روشن باشد و این مدل‌ها نصب باشند:

```powershell
ollama list
```

```
qwen2.5:14b
llama3.2:3b
```

سپس:

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

مرورگر: [http://127.0.0.1:8000](http://127.0.0.1:8000)

## استفاده

1. برنامه خودش شنوا کوچیک CTC را بارگذاری می‌کند.
2. **شروع** را بزنید، فارسی صحبت کنید، **توقف** را بزنید.
3. **آزمایش LLM** همان متن را به `qwen2.5:14b` و `llama3.2:3b` می‌فرستد.
4. برای هر مدل زمان پاسخ (سرعت) و نسبت حروف فارسی (دقت زبان) نشان داده می‌شود.

اگر Ollama روی سیستم دیگری است:

```powershell
$env:OLLAMA_HOST = "http://127.0.0.1:11434"
```

## تست

```powershell
py -m unittest discover -s tests -v
```
