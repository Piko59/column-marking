"""Pytest kök yapılandırması.

config.py, OPENROUTER_API_KEY tanımlı değilse import anında RuntimeError fırlatıyor
(main.py, classifier.pipeline, classifier.llm hepsi config'i import ediyor). Testler
gerçek bir API anahtarına ihtiyaç duymaz; bu yüzden test koleksiyonu başlamadan önce
sahte bir anahtar enjekte ediyoruz.
"""

import os

os.environ.setdefault("OPENROUTER_API_KEY", "test-key-for-pytest")
os.environ.setdefault("QWEN_MODEL", "test-model")
