import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from app.audio import int16_bytes_to_float32, normalize_audio, resample_linear
from app.discovery import detect_engine, find_models_dir, find_shenava_ctc, scan_models


def touch(path: Path, name: str) -> Path:
    file_path = path / name
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(b"x")
    return file_path


class AudioTests(unittest.TestCase):
    def test_resample_changes_length(self):
        samples = np.linspace(-0.2, 0.2, 16000, dtype=np.float32)
        out = resample_linear(samples, 16000, 8000)
        self.assertEqual(out.size, 8000)

    def test_normalize_stereo_int16(self):
        stereo = np.array([[1000, -1000], [2000, -2000]], dtype=np.int16)
        out = normalize_audio(stereo, 8000)
        self.assertEqual(out.ndim, 1)
        self.assertGreater(out.size, 0)

    def test_int16_roundtrip_bytes(self):
        raw = np.array([0, 16384, -16384], dtype=np.int16).tobytes()
        floats = int16_bytes_to_float32(raw)
        self.assertAlmostEqual(float(floats[1]), 0.5, places=2)


class DiscoveryTests(unittest.TestCase):
    def test_detect_vosk(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            touch(root, "am/final.mdl")
            touch(root, "conf/model.conf")
            engine, files, _note = detect_engine(root)
            self.assertEqual(engine, "vosk")
            self.assertTrue(files["model_dir"].endswith(root.name) or Path(files["model_dir"]) == root)

    def test_detect_whisper_ct2(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            touch(root, "model.bin")
            touch(root, "config.json")
            engine, _files, _note = detect_engine(root)
            self.assertEqual(engine, "whisper_ct2")

    def test_detect_sherpa_ctc(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            touch(root, "model.onnx")
            touch(root, "tokens.txt")
            engine, files, _note = detect_engine(root)
            self.assertEqual(engine, "sherpa_ctc")
            self.assertIn("model", files)

    def test_detect_sherpa_rnnt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            touch(root, "encoder.onnx")
            touch(root, "decoder.onnx")
            touch(root, "joiner.onnx")
            touch(root, "tokens.txt")
            engine, files, _note = detect_engine(root)
            self.assertEqual(engine, "sherpa_rnnt")
            self.assertEqual(Path(files["encoder"]).name, "encoder.onnx")

    def test_detect_nemo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            touch(root, "phaseA_rnnt_warmup.nemo")
            touch(root, "shenava-koochik-v1.5.nemo")
            engine, files, _note = detect_engine(root)
            self.assertEqual(engine, "nemo")
            self.assertTrue(files["nemo"].endswith("shenava-koochik-v1.5.nemo"))

    def test_detect_piper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "piper-voice-fa"
            root.mkdir()
            touch(root, "fa.onnx")
            touch(root, "fa.onnx.json")
            engine, _files, _note = detect_engine(root)
            self.assertEqual(engine, "piper_tts")

    def test_scan_skips_piper_as_unusable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vosk = root / "vosk-model-fa"
            vosk.mkdir()
            touch(vosk, "am/final.mdl")
            piper = root / "piper-voice-fa"
            piper.mkdir()
            touch(piper, "voice.onnx.json")
            _path, models = scan_models(root)
            by_id = {item.id: item for item in models}
            self.assertTrue(by_id["vosk-model-fa"].usable)
            self.assertFalse(by_id["piper-voice-fa"].usable)

    def test_find_shenava_ctc_prefers_named_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctc = root / "shenava-koochik-ctc"
            ctc.mkdir()
            touch(ctc, "model.onnx")
            touch(ctc, "tokens.txt")
            other = root / "vosk-model-fa"
            other.mkdir()
            touch(other, "am/final.mdl")
            _path, models = scan_models(root)
            chosen = find_shenava_ctc(models)
            self.assertIsNotNone(chosen)
            self.assertEqual(chosen.id, "shenava-koochik-ctc")
            self.assertEqual(chosen.engine, "sherpa_ctc")

    def test_find_models_dir_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "vosk-model-fa").mkdir()
            with patch.dict("os.environ", {"MODELS_DIR": str(root)}):
                found = find_models_dir()
            self.assertEqual(found, root.resolve())


if __name__ == "__main__":
    unittest.main()
