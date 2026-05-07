import os
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
import subprocess
from google import genai
from google.genai import types


import github_podcast
from dotenv import load_dotenv



KOMUGIKO_RSS = "https://feeds.megaphone.fm/TBS7609676437"

def fetch_komugiko_latest():
    print("Fetching Komugiko RSS...")
    req = urllib.request.Request(KOMUGIKO_RSS, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as response:
        xml_data = response.read()
    
    root = ET.fromstring(xml_data)
    items = root.findall('.//item')
    if not items:
        return None, None, None
        
    latest = items[0]
    title = latest.find('title').text
    guid = latest.find('guid').text if latest.find('guid') is not None else title
    enclosure = latest.find('enclosure')
    mp3_url = enclosure.get('url') if enclosure is not None else None
    
    return title, mp3_url, guid

def download_file(url, local_filename):
    print(f"Downloading {url} to {local_filename}...")
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as response, open(local_filename, 'wb') as out_file:
        data = response.read()
        out_file.write(data)
    print("Download complete.")

def generate_summary_from_audio(client, audio_file_path):
    print("Uploading massive audio to Gemini...")
    uploaded_file = client.files.upload(file=audio_file_path)
    
    prompt = """
あなたはエリート・オーディオブリーフィング・アナウンサーです。提供されたポッドキャスト音声（約2.5時間）を深く分析し、内容の密度が極めて高い【5分間（文字数目安：1500〜2000字程度）】の日本語ブリーフィング・スクリプトを作成してください。
単なる時系列の要約ではなく、以下の4つのセクションに論理的に構造化してください。
出力は「Scale Markdown」形式（TTS読み上げに最適化され、記号を含まない純粋なテキスト）で、すべて日本語で記述してください。

### 構成ルール:
1. **核心となる結論 (The Core Thesis):** 冒頭で、このエピソードの絶対的な核心ポイントや結論を1〜2文で明確に述べること。
2. **3つの重要な洞察 (The 3 Key Insights):** 議論された中で最も重要な3つの洞察や構造的な背景を抽出する。「第一に」「第二に」「第三に」といった自然なつなぎ言葉を使って明確に解説すること。
3. **だから何なのか？ (The "So What?"):** これらの議論が持つ、社会やビジネス、リスナーの未来に対するより広い意味や影響（インプリケーション）を解説すること。
4. **黄金の引用 (The Golden Quote):** エピソード内で語られた中で、最も印象的で具体的な引用、データポイント、またはエピソードを1つだけ取り上げて締めくくること。

### Scale Markdown フォーマットルール:
- 純粋なテキストのみを出力すること。`#`、`##`、`*`、`-`、`>` などのマークダウン記号は【一切使用しない】こと。
- 箇条書きではなく、自然に読み上げられる文章の流れ（トランジション）を使用すること。
- 日本語のTTSエンジンが自然に読めるように、無駄な解説やスクリプト以外の文（「はい、作成しました」等）は含めないこと。
"""
    
    print("Requesting 5-minute Japanese summary from Gemini...")
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=[uploaded_file, prompt]
    )
    
    summary = response.text
    
    try:
        client.files.delete(name=uploaded_file.name)
    except:
        pass
        
    return summary

def generate_audio(client, text):
    print("Generating audio with Gemini TTS (Charon voice) in Japanese...")
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash-preview-tts',
            contents=[text],
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name="Charon"
                        )
                    )
                )
            )
        )
        for part in response.candidates[0].content.parts:
            if part.inline_data:
                return part.inline_data.data
    except Exception as e:
        print(f"Failed to generate TTS audio: {e}")
        return None
    return None

def main():
    if not os.environ.get("GEMINI_API_KEY"):
        print("Error: GEMINI_API_KEY environment variable not set.")
        return

    state_file = os.path.join(os.path.dirname(__file__), "last_komugiko_guid.txt")
    title, mp3_url, current_guid = fetch_komugiko_latest()
    
    if not title or not mp3_url:
        print("Failed to fetch latest episode.")
        return

    # Check if this podcast has already been processed
    if current_guid and os.path.exists(state_file):
        with open(state_file, "r") as f:
            last_guid = f.read().strip()
        if current_guid == last_guid:
            print("No new Komugiko episode detected. Exiting.")
            return

    print(f"Latest Episode: {title}")
    
    local_audio = os.path.join(os.path.dirname(__file__), "temp_komugiko_daily.mp3")
    download_file(mp3_url, local_audio)
    
    client = genai.Client()
    
    summary_text = generate_summary_from_audio(client, local_audio)
    
    display_title = f"コムギコ: {title}"
    full_text_for_feed = f"**{display_title}**\n\n" + summary_text
    
    import datetime
    date_str = datetime.datetime.now().strftime("%Y年%-m月%-d日")
    spoken_text = f"これは「コムギコ、資本主義をハックしろ」。{date_str}のエピソードです。" + summary_text.replace("**", "")
    wav_bytes = generate_audio(client, spoken_text)
    if not wav_bytes:
        print("Failed to generate audio bytes.")
        return
        
    timestamp = int(time.time())
    wav_filename = os.path.join(os.path.dirname(__file__), f"temp_{timestamp}.wav")
    mp3_filename = os.path.join(os.path.dirname(__file__), f"temp_{timestamp}.mp3")
    
    with open(wav_filename, "wb") as f:
        f.write(wav_bytes)
        
    print("Compressing and speeding up audio to MP3...")
    subprocess.run([
        "ffmpeg", "-y", "-f", "s16le", "-ar", "24000", "-ac", "1", 
        "-i", wav_filename, "-filter:a", "atempo=1.25", "-b:a", "128k", mp3_filename
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    mp3_bytes = None
    if os.path.exists(mp3_filename):
        with open(mp3_filename, "rb") as f:
            mp3_bytes = f.read()
        os.remove(wav_filename)
        os.remove(mp3_filename)
        if os.path.exists(local_audio):
            os.remove(local_audio)
    else:
        print("FFmpeg failed!")
        return
        
    print(f"Publishing episode '{display_title}' to GitHub Pages podcast feed...")
    github_podcast.publish_episode(display_title, full_text_for_feed, mp3_bytes)
    
    # Update state file
    if current_guid:
        with open(state_file, "w") as f:
            f.write(current_guid)
            
    print("Done!")

if __name__ == "__main__":
    main()
