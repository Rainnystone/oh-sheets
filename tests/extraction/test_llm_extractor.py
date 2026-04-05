# tests/extraction/test_llm_extractor.py
import json
from unittest.mock import patch
from scripts.extraction.llm_extractor import extract_data

@patch('scripts.extraction.llm_extractor.genai.Client')
def test_extract_data(mock_client_class):
    # Mocking google.genai.Client response
    mock_response = type('Response', (), {'text': '{"FieldA": "Value"}'})()
    mock_client = mock_client_class.return_value
    mock_client.models.generate_content.return_value = mock_response
    
    result = extract_data("Dummy Prompt")
    assert result == {"FieldA": "Value"}
