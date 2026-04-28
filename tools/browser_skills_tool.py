#!/usr/bin/env python3
"""
Browser Domain Skills Tool

Enables the agent to persist and retrieve stable selectors or action sequences
for specific domains (e.g., Amazon, GitHub, LinkedIn). This prevents the agent
from having to re-discover how to navigate complex sites in every session.

Inspired by browser-harness domain-skills.
"""

import json
import os
import logging
from typing import Any, Dict, Optional
from pathlib import Path
from tools.registry import registry, tool_error
from hermes_constants import get_hermes_home

logger = logging.getLogger(__name__)

def get_skills_path() -> Path:
    """Return the path to the browser skills JSON file in HERMES_HOME."""
    path = get_hermes_home() / "browser_skills.json"
    if not path.exists():
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump({}, f)
        except Exception as e:
            logger.error(f"Failed to create browser_skills.json: {e}")
    return path

def load_skills() -> Dict[str, Any]:
    """Load browser skills from disk."""
    path = get_skills_path()
    try:
        if not path.exists():
            return {}
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading browser skills: {e}")
        return {}

def save_skills(skills: Dict[str, Any]):
    """Save browser skills to disk."""
    path = get_skills_path()
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(skills, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error saving browser skills: {e}")

def browser_manage_skills(
    action: str,
    domain: Optional[str] = None,
    skill_name: Optional[str] = None,
    selector: Optional[str] = None,
    description: Optional[str] = None,
    **kwargs
) -> str:
    """
    Manage domain-specific navigation skills.
    
    Actions:
    - save: Persist a stable selector for a specific domain.
    - get: Retrieve all skills for a given domain.
    - list: List all domains and their skills.
    - delete: Remove a specific skill.
    """
    skills = load_skills()
    
    if action == "save":
        if not domain or not skill_name or not selector:
            return tool_error("Missing required parameters for 'save' action: domain, skill_name, and selector are required.")
        
        # Clean domain (remove protocol and trailing slashes)
        clean_domain = domain.lower().replace("https://", "").replace("http://", "").split("/")[0]
        
        if clean_domain not in skills:
            skills[clean_domain] = {}
        
        skills[clean_domain][skill_name] = {
            "selector": selector,
            "description": description or "",
            "last_updated": os.path.getmtime(get_skills_path()) if os.path.exists(get_skills_path()) else 0
        }
        save_skills(skills)
        return json.dumps({
            "success": True, 
            "message": f"Skill '{skill_name}' saved for domain '{clean_domain}'.",
            "domain": clean_domain,
            "skill": skills[clean_domain][skill_name]
        }, ensure_ascii=False)
    
    elif action == "get":
        if not domain:
            return tool_error("The 'domain' parameter is required for 'get' action.")
        clean_domain = domain.lower().replace("https://", "").replace("http://", "").split("/")[0]
        domain_skills = skills.get(clean_domain, {})
        return json.dumps({
            "success": True, 
            "domain": clean_domain, 
            "skills": domain_skills,
            "count": len(domain_skills)
        }, ensure_ascii=False)
    
    elif action == "list":
        return json.dumps({
            "success": True, 
            "domains": list(skills.keys()),
            "total_skills": sum(len(s) for s in skills.values())
        }, ensure_ascii=False)
    
    elif action == "delete":
        if not domain or not skill_name:
            return tool_error("Missing required parameters for 'delete' action: domain and skill_name are required.")
        clean_domain = domain.lower().replace("https://", "").replace("http://", "").split("/")[0]
        if clean_domain in skills and skill_name in skills[clean_domain]:
            del skills[clean_domain][skill_name]
            if not skills[clean_domain]:
                del skills[clean_domain]
            save_skills(skills)
            return json.dumps({"success": True, "message": f"Skill '{skill_name}' deleted from domain '{clean_domain}'."})
        return tool_error(f"Skill '{skill_name}' not found for domain '{clean_domain}'.")
    
    return tool_error("Unrecognized action. Supported actions: 'save', 'get', 'list', 'delete'.")

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

BROWSER_SKILLS_SCHEMA = {
    "name": "browser_manage_skills",
    "description": (
        "Persist and retrieve stable CSS/XPath selectors or navigation patterns for specific domains. "
        "Inspired by browser-harness, this tool allows the agent to 'remember' how to interact with "
        "complex websites (e.g., login buttons, search inputs, checkout flows) across sessions. "
        "Use this to avoid re-discovering the same elements repeatedly."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string", 
                "enum": ["save", "get", "list", "delete"],
                "description": "The action to perform."
            },
            "domain": {
                "type": "string", 
                "description": "The domain name (e.g., 'amazon.com', 'github.com')."
            },
            "skill_name": {
                "type": "string", 
                "description": "A unique name for the skill (e.g., 'add_to_cart_button', 'search_box')."
            },
            "selector": {
                "type": "string", 
                "description": "The stable CSS selector or XPath for the element."
            },
            "description": {
                "type": "string", 
                "description": "Optional description of what this skill/selector does."
            }
        },
        "required": ["action"]
    }
}

registry.register(
    name="browser_manage_skills",
    toolset="browser",
    schema=BROWSER_SKILLS_SCHEMA,
    handler=lambda args, **kw: browser_manage_skills(**args),
    emoji="🧠"
)
