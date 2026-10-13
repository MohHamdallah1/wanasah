"""Lifecycle HTTP placeholder; safety semantics are intentionally not invented in Wave 1."""
from fastapi import APIRouter

router = APIRouter()

__all__ = ["router"]
