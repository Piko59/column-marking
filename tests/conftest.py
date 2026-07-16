"""Pytest kök yapılandırması.

config.py, LLM_BASE_URL / LLM_API_KEY tanımlı değilse import anında RuntimeError
fırlatıyor (main.py, classifier.pipeline, classifier.llm hepsi config'i import ediyor).
Testler gerçek bir uca ihtiyaç duymaz; bu yüzden test koleksiyonu başlamadan önce
sahte bağlantı bilgileri enjekte ediyoruz.
"""

import os

os.environ.setdefault("LLM_BASE_URL", "http://test-llm.invalid/v1")
os.environ.setdefault("LLM_API_KEY", "test-key-for-pytest")
os.environ.setdefault("LLM_MODEL", "test-model")
