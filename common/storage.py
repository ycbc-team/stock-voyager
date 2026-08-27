#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared filesystem helpers for build/site, build/data, build/cache and common/cache.

`build/cache` stores request-level daily artifacts that can be regenerated freely.
`common/cache` stores long-lived reference caches; callers decide whether to expire
them, while the default behavior is to keep them until a business rule says refresh.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import time
from typing import Any, Dict, Optional


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD_DIR = os.path.join(PROJECT_ROOT, "build")
SITE_DIR = os.path.join(BUILD_DIR, "site")
DATA_DIR = os.path.join(BUILD_DIR, "data")
REQUEST_CACHE_DIR = os.path.join(BUILD_DIR, "cache")
CACHE_DIR = os.path.join(PROJECT_ROOT, "common", "cache")
CACHE_SCHEMA_VERSION = 1


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def default_build_dir() -> str:
    return ensure_dir(BUILD_DIR)


def default_site_dir() -> str:
    return ensure_dir(SITE_DIR)


def default_data_dir() -> str:
    return ensure_dir(DATA_DIR)


def default_request_cache_dir() -> str:
    return ensure_dir(REQUEST_CACHE_DIR)


def default_cache_dir() -> str:
    return ensure_dir(CACHE_DIR)


def site_path(filename: str) -> str:
    return os.path.join(default_site_dir(), filename)


def data_path(filename: str) -> str:
    return os.path.join(default_data_dir(), filename)


def request_cache_path(filename: str) -> str:
    return os.path.join(default_request_cache_dir(), filename)


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


def _now_text() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _wrap_cache_payload(payload: Any, scope: str, source: Optional[str], ttl_hours: Optional[int], tags: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "cache_scope": scope,
        "saved_at": _now_text(),
        "ttl_hours": ttl_hours,
    }
    if source:
        meta["source"] = source
    if tags:
        meta.update(tags)
    return {"_meta": meta, "data": payload}


def _unwrap_cache_payload(payload: Any) -> Any:
    if isinstance(payload, dict) and "_meta" in payload and "data" in payload:
        return payload.get("data")
    return payload


def _read_wrapped_payload(path: str) -> Optional[Any]:
    if not os.path.exists(path):
        return None
    try:
        return read_json(path)
    except Exception:
        return None


def load_data_json(filename: str) -> Optional[Any]:
    payload = _read_wrapped_payload(data_path(filename))
    if payload is None:
        return None
    return _unwrap_cache_payload(payload)


def save_data_json(filename: str, payload: Any, *, source: Optional[str] = None, tags: Optional[Dict[str, Any]] = None) -> str:
    wrapped = _wrap_cache_payload(payload, "page_data", source, None, tags)
    return write_json(data_path(filename), wrapped)


def load_build_json(filename: str) -> Optional[Any]:
    return load_request_cache_json(filename)


def save_build_json(filename: str, payload: Any) -> str:
    return save_request_cache_json(filename, payload)


def load_request_cache_json(filename: str, max_age_hours: Optional[int] = None) -> Optional[Any]:
    path = request_cache_path(filename)
    payload = _read_wrapped_payload(path)
    if payload is None:
        return None
    if max_age_hours is not None:
        age_seconds = time.time() - os.path.getmtime(path)
        if age_seconds > max_age_hours * 3600:
            return None
    return _unwrap_cache_payload(payload)


def save_request_cache_json(filename: str, payload: Any, *, source: Optional[str] = None, ttl_hours: Optional[int] = None, tags: Optional[Dict[str, Any]] = None) -> str:
    wrapped = _wrap_cache_payload(payload, "request_cache", source, ttl_hours, tags)
    return write_json(request_cache_path(filename), wrapped)


def load_cache_json(filename: str, max_age_hours: Optional[int] = None) -> Optional[Any]:
    path = cache_path(filename)
    payload = _read_wrapped_payload(path)
    if payload is None:
        return None
    if max_age_hours is not None:
        age_seconds = time.time() - os.path.getmtime(path)
        if age_seconds > max_age_hours * 3600:
            return None
    return _unwrap_cache_payload(payload)


def save_cache_json(filename: str, payload: Any, *, source: Optional[str] = None, ttl_hours: Optional[int] = None, tags: Optional[Dict[str, Any]] = None) -> str:
    wrapped = _wrap_cache_payload(payload, "static_cache", source, ttl_hours, tags)
    return write_json(cache_path(filename), wrapped)
