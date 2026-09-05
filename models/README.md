# مدل‌های گفتار فارسی

پوشه مدل‌ها را اینجا بگذارید، یا مسیر را در `config.json` تنظیم کنید:

```json
{
  "models_dir": "C:\\Users\\omid\\Documents\\appointment\\models"
}
```

برای تماس صوتی (`شروع تماس`) حداقل مدل CTC شنوا لازم است:

```bash
./scripts/download_shenava_ctc.sh
# یا روی سرور:
MODELS_DIR=/opt/persian-type/models ./scripts/download_shenava_ctc.sh
```

سپس `MODELS_DIR` را به ریشه مدل‌ها تنظیم کنید و `POST /api/boot` بزنید (فرانت‌اند هنگام باز شدن صفحه این کار را می‌کند).

مدل‌های پشتیبانی‌شده:

| پوشه | موتور |
|------|--------|
| `vosk-model-fa` | Vosk |
| `whisper-persian-v4-ct2` | Faster-Whisper (CTranslate2) |
| `shenava-koochik-ctc` | sherpa-onnx CTC (**ترجیح برای تماس صوتی**) |
| `shenava-koochik-v1.5` | sherpa-onnx RNNT یا فایل `.nemo` |
| `piper-voice-fa` | تبدیل متن به گفتار — برای تایپ استفاده نمی‌شود |

منبع CTC: [PersianML/Shenava-Koochik-v1.0-sherpa-onnx](https://huggingface.co/PersianML/Shenava-Koochik-v1.0-sherpa-onnx) (`model.onnx` + `tokens.txt`).
