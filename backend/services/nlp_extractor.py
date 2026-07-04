import json
import re
import asyncio
from typing import List, Dict, Any, Tuple
import httpx
from openai import AsyncOpenAI
from backend.core.config import YANDEX_API_KEY, YANDEX_FOLDER_ID, YANDEX_GPT_MODEL_120B, GEMINI_API_KEY

class GeminiCompletions:
    def __init__(self, api_key: str):
        self.api_key = api_key

    async def create(self, model=None, messages=None, temperature=0.1, max_tokens=1000, **kwargs):
        system_instruction = None
        contents = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            if role == "system":
                system_instruction = content
            else:
                gemini_role = "model" if role in ["assistant", "model"] else "user"
                contents.append({
                    "role": gemini_role,
                    "parts": [{"text": content}]
                })
        
        if not contents:
            contents.append({
                "role": "user",
                "parts": [{"text": "Process request."}]
            })

        # Ensure maxOutputTokens is at least 2048 to allow for thinking + generation
        gemini_max_tokens = max(max_tokens, 2048) if max_tokens else 2048

        body = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": gemini_max_tokens
            }
        }
        if system_instruction:
            body["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }

        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent"
        headers = {
            "Content-Type": "application/json",
            "X-goog-api-key": self.api_key
        }

        async with httpx.AsyncClient() as client:
            res = await client.post(url, json=body, headers=headers, timeout=60.0)
            res.raise_for_status()
            data = res.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]

        class MockMessage:
            def __init__(self, content):
                self.content = content

        class MockChoice:
            def __init__(self, content):
                self.message = MockMessage(content)

        class MockResponse:
            def __init__(self, content):
                self.choices = [MockChoice(content)]

        return MockResponse(text)

class GeminiChatCompletions:
    def __init__(self, api_key: str):
        self.completions = GeminiCompletions(api_key)

class GeminiClient:
    def __init__(self, api_key: str):
        self.chat = GeminiChatCompletions(api_key)

class NLPExtractor:
    def __init__(self, api_key: str = YANDEX_API_KEY, folder_id: str = YANDEX_FOLDER_ID):
        # Prioritize Yandex API if credentials are provided and not placeholders
        if api_key and api_key != "your_yandex_api_key_here":
            self.client = AsyncOpenAI(
                api_key=api_key,
                base_url="https://ai.api.cloud.yandex.net/v1",
                project=folder_id
            )
            self.model_id = YANDEX_GPT_MODEL_120B
        elif GEMINI_API_KEY:
            self.client = GeminiClient(api_key=GEMINI_API_KEY)
            self.model_id = "gemini-3.1-flash-lite"
        else:
            self.client = AsyncOpenAI(
                api_key=api_key,
                base_url="https://ai.api.cloud.yandex.net/v1",
                project=folder_id
            )
            self.model_id = YANDEX_GPT_MODEL_120B


    async def extract_entities_and_relations(self, chunk_text: str) -> Dict[str, Any]:
        """Asynchronously calls GPT 120B to extract entities and relations from a text chunk."""
        
        system_prompt = (
            "Вы — ведущий эксперт-лингвист в области горной металлургии. Ваша задача — проанализировать научный текст и извлечь сущности и связи.\n\n"
            "Доступные типы сущностей:\n"
            "- Material: вещества, металлы, растворы, шлаки, штейны, руды (например: никель, медь, сульфат никеля, хлоридный электролит, шлак)\n"
            "- Process: химические или физические процессы (например: электроэкстракция, выщелачивание, автоклавное окисление, плавка, фильтрация)\n"
            "- Equipment: оборудование и агрегаты (например: ванна электроэкстракции, печь Ванюкова, печь взвешенной плавки, мельница)\n"
            "- Property: параметры, числовые условия и свойства (например: плотность тока: 300 А/м2, pH: 2, температура: 900°C, концентрация сульфатов: 200 мг/л, прочность: 620 МПа)\n"
            "- Expert: авторы, исследователи, лаборатории (например: Евграфова А.К., Институт Гипроникель)\n"
            "- Facility: промышленные объекты, рудники, заводы (например: рудник Кайерканский, Кольская ГМК, завод Long Harbour)\n\n"
            "Доступные типы связей:\n"
            "- uses_material: процесс использует материал\n"
            "- operates_at_condition: процесс/оборудование работает при определенном условии/параметре (Property)\n"
            "- produces_output: процесс дает на выходе материал или свойство\n"
            "- located_at: объект/оборудование находится в географическом пункте/установке\n\n"
            "Ответ предоставьте строго в формате JSON, без лишних слов, разметки markdown или объяснений. Пример формата:\n"
            "{\n"
            "  \"entities\": [\n"
            "    {\"type\": \"Material\", \"value\": \"никель\"},\n"
            "    {\"type\": \"Process\", \"value\": \"электроэкстракция\"},\n"
            "    {\"type\": \"Property\", \"value\": \"pH: 2\"}\n"
            "  ],\n"
            "  \"relations\": [\n"
            "    {\"source\": \"электроэкстракция\", \"type\": \"uses_material\", \"target\": \"никель\"}\n"
            "  ]\n"
            "}"
        )

        # Retry logic
        for attempt in range(3):
            try:
                response = await self.client.chat.completions.create(
                    model=self.model_id,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"Текст для анализа:\n{chunk_text}"}
                    ],
                    temperature=0.1,
                    max_tokens=1000
                )
                
                content = response.choices[0].message.content
                if not content:
                    continue
                    
                # Clean JSON string (remove markdown code blocks if model returned them)
                clean_json = content.strip()
                if clean_json.startswith("```json"):
                    clean_json = clean_json[7:]
                if clean_json.endswith("```"):
                    clean_json = clean_json[:-3]
                clean_json = clean_json.strip()
                
                parsed_data = json.loads(clean_json)
                
                # Apply regex correction for numerical properties to ensure precision
                self._enrich_numeric_properties(chunk_text, parsed_data)
                
                return parsed_data
            except Exception as e:
                print(f"Extraction attempt {attempt+1} failed: {e}")
                await asyncio.sleep(1)
                
        # Return fallback empty structure
        return {"entities": [], "relations": []}

    def _enrich_numeric_properties(self, text: str, data: Dict[str, Any]):
        """Runs regex patterns over the text chunk to ensure important numerical parameters are not missed."""
        existing_values = {e["value"].lower() for e in data.get("entities", []) if e["type"] == "Property"}
        
        # Regex patterns for temperature, pH, concentrations, current density, etc.
        patterns = [
            (r'\b(\d+[-–]\d+\s*°C|\d+\s*°C|\d+\s*К)\b', "Property", "temperature"),
            (r'\b(pH\s*[:=]?\s*\d+([.,]\d+)?)\b', "Property", "pH"),
            (r'\b(\d+\s*А/м[²2]|\d+[-–]\d+\s*А/м[²2])\b', "Property", "current_density"),
            (r'\b(\d+([.,]\d+)?\s*(?:мг/л|мг/дм³|г/л|%|МПа|HB))\b', "Property", "value_range"),
            (r'\b(?:[<>]|≤|≥)\s*\d+([.,]\d+)?\s*(?:мг/л|мг/дм³|г/л|%|МПа|HB)\b', "Property", "threshold")
        ]
        
        for pattern, ent_type, label in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for m in matches:
                val = m[0] if isinstance(m, tuple) else m
                val_clean = val.strip()
                if val_clean.lower() not in existing_values:
                    data.setdefault("entities", []).append({
                        "type": ent_type,
                        "value": val_clean
                    })
                    existing_values.add(val_clean.lower())
