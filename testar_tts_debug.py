"""
Testa múltiplas vozes Wavenet en-US com a mesma frase de true crime.
"""
import os
import base64
from dotenv import load_dotenv
import requests

load_dotenv()
key = os.getenv('GOOGLE_TTS_API_KEY')

# Frase mais dramática pra testar cada voz
texto = ("On the morning of May 2nd, 2025, a mother in rural Nova Scotia "
         "called police to report that her two young children had "
         "wandered away from their home. Nearly a year later, no one "
         "has found them.")

# Vozes pra comparar (todas Wavenet, custo idêntico)
vozes = [
    "en-US-Wavenet-A",
    "en-US-Wavenet-B",
    "en-US-Wavenet-D",
    "en-US-Wavenet-I",
    "en-US-Wavenet-J",
]

for voz in vozes:
    payload = {
        "input": {"text": texto},
        "voice": {"languageCode": "en-US", "name": voz},
        "audioConfig": {"audioEncoding": "MP3"}
    }

    url = f'https://texttospeech.googleapis.com/v1/text:synthesize?key={key}'
    r = requests.post(url, json=payload)

    if r.status_code == 200:
        audio_bytes = r.json().get('audioContent', '')
        arquivo = f"teste_{voz}.mp3"
        with open(arquivo, 'wb') as f:
            f.write(base64.b64decode(audio_bytes))
        print(f"OK - {arquivo}")
    else:
        print(f"ERRO {voz}: {r.status_code}")

print(f"\nTotal de chars por voz: {len(texto)}")
print(f"Total de chars gasto: {len(texto) * len(vozes)}")