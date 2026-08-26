#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared filesystem helpers for build/ and common/cache/."""
from __future__ import annotations

import json
import os
import time
from typing import Any, Optional


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD_DIR = os.path.join(PROJECT_ROOT, "build")
CACHE_DIR = os.path.join(PROJECT_ROOT, "common", "cache")


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def default_build_dir() -> str:
    return ensure_dir(BUILD_DIR)


def default_cache_dir() -> str:
    return ensure_dir(CACHE_DIR)


def build_path(filename: str) -> str:
    return os.path.join(default_build_dir(), filename)


def cache_path(filename: str) -> str:
    return os.path.join(default_cache_dir(), filename)


def read_json(path: str) -> Any:
    with open(path, encoding="utf-8") as file:
        return json.load(file)


def write_json(path: str, payload: Any) -> str:
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        ensure_dir(directory)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
    return path


def load_build_json(filename: str) -> Optional[Any]:
    path = build_path(filename)
    if not os.path.exists(path):
        return None
    try:
        return read_json(path)
    except Exception:
        return None


def save_build_json(filename: str, payload: Any) -> str:
    return write_json(build_path(filename), payload)


def load_cache_json(filename: str, max_age_hours: Optional[int] = None) -> Optional[Any]:
    path = cache_path(filename)
    if not os.path.exists(path):
        return None
    if max_age_hours is not None:
        age_seconds = time.time() - os.path.getmtime(path)
        if age_seconds > max_age_hours * 3600:
            return None
    try:
        return read_json(path)
    except Exception:
        return None


def save_cache_json(filename: str, payload: Any) -> str:
    return write_json(cache_path(filename), payload)
