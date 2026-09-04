# مدل‌های گفتار فارسی

پوشه مدل‌ها را اینجا بگذارید، یا مسیر را در `config.json` تنظیم کنید:

```json
{
  "models_dir": "C:\\Users\\omid\\Documents\\appointment\\models"
}
```

مدل‌های پشتیبانی‌شده:

| پوشه | موتور |
|------|--------|
| `vosk-model-fa` | Vosk |
| `whisper-persian-v4-ct2` | Faster-Whisper (CTranslate2) |
| `shenava-koochik-ctc` | sherpa-onnx CTC |
| `shenava-koochik-v1.5` | sherpa-onnx RNNT یا فایل `.nemo` |
| `piper-voice-fa` | تبدیل متن به گفتار — برای تایپ استفاده نمی‌شود |
