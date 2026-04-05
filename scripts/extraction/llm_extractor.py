# scripts/extraction/llm_extractor.py
import os
import json
import re

try:
    from google import genai
    from google.genai import types
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

def extract_data(prompt: str) -> dict:
    """Execute extraction by passing prompt to LLM and parsing JSON using google.genai."""
    if not HAS_GENAI:
        raise RuntimeError("google-genai library is not installed.")
        
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is not set.")

    client = genai.Client(api_key=api_key)
    
    # Instruct model to output JSON
    sys_instruct = "You are a precise data extraction system. Output strictly valid JSON."
    
    response = client.models.generate_content(
        model='gemini-2.5-pro',
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=sys_instruct,
            temperature=0.0,
            response_mime_type="application/json",
        ),
    )
    
    text = response.text
    # Clean up markdown code blocks if present
    text = re.sub(r'^```json\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse LLM response as JSON: {e}\nResponse: {response.text}")
