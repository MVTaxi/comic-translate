import dearpygui.dearpygui as dpg
import numpy as np
from typing import List
from .utils.textblock import TextBlock
from .rendering.render import cv2_to_pil
from .utils.translator_utils import encode_image_array, get_raw_text, set_texts_from_json
from .utils.pipeline_utils import get_language_codes
from deep_translator import GoogleTranslator, YandexTranslator
import deepl
import requests


class Translator:
    def __init__(self, client = None, api_key: str = '', region = None):
        self.client = client
        self.api_key = api_key
        self.img_as_llm_input = dpg.get_value("img_as_input_to_llm_checkbox")
        self.region = region    # Used in Microsoft Azure AI Translator

    def get_llm_model(self, translator: str):
        model_map = {
            "GPT-4o": "gpt-4o",
            "GPT-3.5": "gpt-3.5-turbo",
            "Claude-3-Opus": "claude-3-opus-20240229",
            "Claude-3.5-Sonnet": "claude-3-5-sonnet-20240620",
            "Claude-3-Haiku": "claude-3-haiku-20240307",
            "Gemini-1.5-Flash": "gemini-1.5-flash-latest",
            "Gemini-1.5-Pro": "gemini-1.5-pro-latest"
        }
        return model_map.get(translator)
    
    def get_system_prompt(self, source_lang: str, target_lang: str):
        return f"""You are an expert translator who translates {source_lang} to {target_lang}. You pay attention to style, formality, idioms, slang etc and try to convey it in the way a {target_lang} speaker would understand.
        BE MORE NATURAL. NEVER USE 당신, 그녀, 그 or its Japanese equivalents.
        Specifically, you will be translating text OCR'd from a comic. The OCR is not perfect and as such you may receive text with typos or other mistakes.
        To aid you and provide context, You may be given the image of the page and/or extra context about the comic. You will be given a json string of the detected text blocks and the text to translate. Return the json string with the texts translated. DO NOT translate the keys of the json. For each block:
        - If it's already in {target_lang} or looks like gibberish, OUTPUT IT AS IT IS instead
        - DO NOT give explanations
        Do Your Best! I'm really counting on you."""
    
    def get_azure_translation(self, user_prompt: str, source_lang: str, target_lang: str, key: str, region: str, endpoint = 'https://api.cognitive.microsofttranslator.com/'):
        url = endpoint + 'translate'
        # Build the request
        params = {
            'api-version': '3.0',
            'from': source_lang,
            'to': target_lang
        }
        headers = {
            'Ocp-Apim-Subscription-Key': key,
            'Ocp-Apim-Subscription-Region': region,
            'Content-type': 'application/json'
        }
        body = [{
            'text': user_prompt
        }]
        # Send the request and get response
        request = requests.post(url, params=params, headers=headers, json=body)
        response = request.json()
        # Get translation
        translation = response[0]["translations"][0]["text"]
        # Return the translation
        return translation

    def get_gpt_translation(self, user_prompt: str, model: str, system_prompt: str, image: np.ndarray):
        encoded_image = encode_image_array(image)

        if self.img_as_llm_input and model != "gpt-3.5-turbo":
            message = [
                    {"role": "system", "content": [{"type": "text", "text": system_prompt}]},
                    {"role": "user", "content": [{"type": "text", "text": user_prompt}, {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded_image}"}}]}
                ]
        else:
            message = [
                    {"role": "system", "content": [{"type": "text", "text": system_prompt}]},
                    {"role": "user", "content": [{"type": "text", "text": user_prompt}]}
                ]

        response = self.client.chat.completions.create(
            model=model,
            messages=message,
            temperature=1,
            max_tokens=1000,
        )

        translated = response.choices[0].message.content
        return translated
    
    def get_claude_translation(self, user_prompt: str, model: str, system_prompt: str, image: np.ndarray):
        encoded_image = encode_image_array(image)
        media_type = "image/png"

        if self.img_as_llm_input:
            message = [
                {"role": "user", "content": [{"type": "text", "text": user_prompt}, {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": encoded_image}}]}
            ]
        else:
            message = [{"role": "user", "content": [{"type": "text", "text": user_prompt}]}]

        response = self.client.messages.create(
            model = model,
            system = system_prompt,
            messages=message,
            temperature=1,
            max_tokens=1000,
        )
        translated = response.content[0].text
        return translated
    
    def get_gemini_translation(self, user_prompt: str, model: str, system_prompt: str, image):

        generation_config = {
            "temperature": 1,
            "top_p": 0.95,
            "top_k": 0,
            "max_output_tokens": 1000,
            }
        
        safety_settings = [
            {
                "category": "HARM_CATEGORY_HARASSMENT",
                "threshold": "BLOCK_NONE"
                },
            {
                "category": "HARM_CATEGORY_HATE_SPEECH",
                "threshold": "BLOCK_NONE"
                },
            {
                "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                "threshold": "BLOCK_NONE"
                },
            {
                "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                "threshold": "BLOCK_NONE"
                },
        ]

        model_instance = self.client.GenerativeModel(model_name = model, generation_config=generation_config, system_instruction=system_prompt, safety_settings=safety_settings)
        chat = model_instance.start_chat(history=[])
        if self.img_as_llm_input:
            chat.send_message([image, user_prompt])
        else:
            chat.send_message([user_prompt])
        response = chat.last.text

        return response

    def translate(self, blk_list: List[TextBlock], translator: str, source_lang: str, target_lang: str, image: np.ndarray, inpainted_img: np.ndarray, extra_context: str):
        source_lang_code, target_lang_code = get_language_codes(source_lang, target_lang)

        # Non LLM Based
        if translator in ["Google Translate", "DeepL", "Yandex", "Azure AI Translator"]:
            for blk in blk_list:
                text = blk.text.replace(" ", "") if 'zh' in source_lang_code.lower() or source_lang_code.lower() == 'ja' else blk.text
                if translator == "Google Translate":
                    translation = GoogleTranslator(source='auto', target=target_lang_code).translate(text)
                elif translator == "Yandex":
                    translation = YandexTranslator(self.api_key).translate(source='auto', target=target_lang_code, text=text)
                elif translator == "Azure AI Translator":
                    translation = self.get_azure_translation(text, source_lang_code, target_lang_code, self.api_key, self.region)
                else:
                    trans = deepl.Translator(self.api_key)
                    if target_lang == "Chinese (Simplified)":
                        result = trans.translate_text(text, source_lang=source_lang_code, target_lang="zh")
                    elif target_lang == "English":
                        result = trans.translate_text(text, source_lang=source_lang_code, target_lang="EN-US")
                    else:
                        result = trans.translate_text(text, source_lang=source_lang_code, target_lang=target_lang_code)
                    translation = result.text
                if translation is not None:
                    blk.translation = translation
        
        # Handle LLM based translations
        else:
            model = self.get_llm_model(translator)
            entire_raw_text = get_raw_text(blk_list)
            system_prompt = self.get_system_prompt(source_lang, target_lang)
            user_prompt = f"{extra_context}\nMake the translation sound as natural as possible.\nTranslate this:\n{entire_raw_text}"

            if 'GPT' in translator:
                entire_translated_text = self.get_gpt_translation(user_prompt, model, system_prompt, image)

            elif 'Claude' in translator:
                # Adjust image based on source language
                image = image if source_lang_code not in ['zh-CN', 'zh-TW', 'ja', 'ko'] else inpainted_img
                entire_translated_text = self.get_claude_translation(user_prompt, model, system_prompt, image)

            elif 'Gemini' in translator:
                image = image if source_lang_code not in ['zh-CN', 'zh-TW', 'ja', 'ko'] else inpainted_img
                image = cv2_to_pil(image)
                entire_translated_text = self.get_gemini_translation(user_prompt, model, system_prompt, image)

            set_texts_from_json(blk_list, entire_translated_text)

        return blk_list