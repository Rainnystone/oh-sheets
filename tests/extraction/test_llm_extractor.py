# tests/extraction/test_llm_extractor.py
import json
import os
from unittest.mock import patch, MagicMock
from scripts.extraction.llm_extractor import extract_data

@patch('scripts.extraction.llm_extractor.genai.Client')
def test_extract_data(mock_client_class):
    # Set mock API key
    os.environ['GEMINI_API_KEY'] = 'test_key'

    # Mocking google.genai.Client response
    mock_response = MagicMock()
    mock_response.text = '{"FieldA": "Value"}'
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    mock_client_class.return_value = mock_client

    result = extract_data("Dummy Prompt")
    assert result == {"FieldA": "Value"}

    # Cleanup
    del os.environ['GEMINI_API_KEY']
