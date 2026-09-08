#!/usr/bin/env python3
"""Quick diagnostic: test OpenAI translation API call with current config."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

async def test_azure_models_endpoint():
    """Try the Azure AI Foundry serverless /models endpoint."""
    from openai import AsyncOpenAI
    import json

    from oki.config import Settings
    s = Settings()
    api_key = s.azure_openai_api_key or ""
    endpoint = str(s.azure_openai_endpoint or "")
    model = os.environ.get("OKI_AZURE_GPT_DEPLOYMENT", "gpt-4o-mini")

    base_url = endpoint.rstrip("/") + "/models/"
    print(f"Testing Azure AI Foundry models endpoint: {base_url}")
    print(f"Model: {model}")

    client = AsyncOpenAI(base_url=base_url, api_key=api_key or "placeholder")
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "Translate the following to Spanish. Return JSON: {\"translated_text\": \"...\"}"},
            {"role": "user", "content": "Hello, this is a test."},
        ],
        response_format={"type": "json_object"},
        max_tokens=200,
    )
    raw = json.loads(response.choices[0].message.content or "{}")
    print(f"SUCCESS! Translated: {raw.get('translated_text', '')}")

async def main():
    from oki.config import Settings
    settings = Settings()
    print(f"Azure endpoint: {settings.azure_openai_endpoint}")
    print(f"Azure GPT deployment (current .env): {settings.azure_gpt_deployment}")
    print()

    # Test what's in .env first
    print("=== Test 1: current deployment (gpt-4o-mini-transcribe) ===")
    try:
        from oki.providers.openai_translation import OpenAITranslationClient
        client = OpenAITranslationClient(settings)
        result = await client.translate(text="Hello", target_language="es", source_language="en")
        print(f"SUCCESS: {result['translated_text']}")
    except Exception as e:
        print(f"FAILED: {e}")

    print()
    print("=== Test 2: Azure AI Foundry /models/ endpoint with gpt-4o-mini ===")
    try:
        os.environ["OKI_AZURE_GPT_DEPLOYMENT"] = "gpt-4o-mini"
        await test_azure_models_endpoint()
    except Exception as e:
        print(f"FAILED: {e}")

    print()
    print("=== Test 3: Azure AI Foundry /models/ endpoint with gpt-4o ===")
    try:
        os.environ["OKI_AZURE_GPT_DEPLOYMENT"] = "gpt-4o"
        await test_azure_models_endpoint()
    except Exception as e:
        print(f"FAILED: {e}")

asyncio.run(main())
