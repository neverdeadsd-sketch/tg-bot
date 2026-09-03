# -*- coding: utf-8 -*-
"""Русский синтез речи через libespeak-ng (ctypes). Без сети и без платных API."""
import ctypes
import wave
import espeakng_loader as loader

AUDIO_OUTPUT_RETRIEVAL = 1
espeakCHARS_UTF8 = 1
espeakRATE, espeakVOLUME, espeakPITCH, espeakRANGE, espeakPUNCTUATION, espeakCAPITALS, espeakWORDGAP = range(1, 8)

_CB = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(ctypes.c_short),
                       ctypes.c_int, ctypes.c_void_p)


class Espeak:
    def __init__(self, voice=b"ru", rate=160, pitch=42, gap=6):
        self.lib = ctypes.CDLL(str(loader.get_library_path()))
        self.lib.espeak_Initialize.restype = ctypes.c_int
        self.rate_hz = self.lib.espeak_Initialize(
            AUDIO_OUTPUT_RETRIEVAL, 600, str(loader.get_data_path()).encode(), 0)
        if self.rate_hz <= 0:
            raise RuntimeError("espeak_Initialize failed")
        self._buf = bytearray()

        def _cb(wav, n, events):
            if wav and n > 0:
                self._buf += ctypes.string_at(wav, n * 2)
            return 0

        self._cb_ref = _CB(_cb)
        self.lib.espeak_SetSynthCallback(self._cb_ref)
        if self.lib.espeak_SetVoiceByName(voice) != 0:
            raise RuntimeError("voice %r not available" % voice)
        for p, v in ((espeakRATE, rate), (espeakPITCH, pitch),
                     (espeakVOLUME, 100), (espeakRANGE, 60), (espeakWORDGAP, gap)):
            self.lib.espeak_SetParameter(p, v, 0)

    def say(self, text, path):
        self._buf = bytearray()
        b = text.encode("utf-8")
        self.lib.espeak_Synth(b, len(b) + 1, 0, 0, 0, espeakCHARS_UTF8, None, None)
        self.lib.espeak_Synchronize()
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.rate_hz)
            w.writeframes(bytes(self._buf))
        return len(self._buf) / 2 / self.rate_hz


if __name__ == "__main__":
    e = Espeak()
    d = e.say("Photoshop — это не фильтр для селфи. Это профессиональная кухня ресторана.",
              "/tmp/probe_ru.wav")
    print("sample rate:", e.rate_hz, "| длительность, с:", round(d, 2))
