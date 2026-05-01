from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.prompts.registry import (
    clear_prompt_cache,
    get_prompt,
    list_prompts,
    save_prompt_override,
)

router = APIRouter(prefix="/prompts", tags=["prompts"])


@router.get("")
def all_prompts():
    return {"prompts": list_prompts()}


@router.post("/_reload")
def reload_prompts():
    """Force-clear the in-process prompt cache and re-list. Useful after
    editing the YAML files on disk or pasting a new override row directly."""
    cleared = clear_prompt_cache()
    return {"ok": True, "cleared": cleared, "prompts": list_prompts()}


@router.get("/{key}")
def one_prompt(key: str):
    try:
        return get_prompt(key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="prompt not found")


class UpdatePromptRequest(BaseModel):
    template: str
    edited_by: str = "ui"


@router.put("/{key}")
def update_prompt(key: str, req: UpdatePromptRequest):
    try:
        get_prompt(key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="prompt not found")
    ok = save_prompt_override(key, req.template, req.edited_by)
    if not ok:
        raise HTTPException(status_code=500, detail="save failed")
    return {"ok": True, "key": key}
