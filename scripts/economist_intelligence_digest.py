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

load_dotenv()

RSS_URL = "https://feeds.acast.com/public/shows/the-intelligence-from-the-economist"

def fetch_latest():
    print("Fetching The Intelligence RSS...")
    req = urllib.request.Request(RSS_URL, headers={'User-Agent': 'Mozilla/5.0'})
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
    print("Uploading audio to Gemini...")
    uploaded_file = client.files.upload(file=audio_file_path)
    
    prompt = """
You are an elite audio briefing announcer. Analyze the provided podcast audio from "The Intelligence" and create a highly condensed, intellectually dense 3-4 minute briefing script in English.
Do NOT simply provide a chronological summary. Structure the script logically into the following 4 sections.
Output the script ONLY in English and ONLY in "Scale Markdown" format (optimized for TTS reading with no markdown symbols).

### Structure Rules:
1. **The Core Thesis:** At the very beginning, state the absolute core point or conclusion of the episode in 1-2 clear sentences.
2. **The 3 Key Insights:** Extract the three most critical insights or structural background elements discussed by the reporter. Explain them clearly using transitional words like "First,", "Second,", and "Third,".
3. **The "So What?":** Explain the broader implications of these events. What does this mean for the future of the industry, society, or the listeners?
4. **The Golden Quote:** Conclude with exactly one highly memorable, specific quote, data point, or anecdote mentioned in the episode by the reporter or guest.

### Scale Markdown Formatting Rules:
- Output only plain text. Do NOT use `#`, `##`, `*`, `-`, `>`, or any other markdown symbols.
- Use natural spoken transitions instead of bullet points.
- Ensure all text is naturally readable by an English TTS engine. Do not include any explanations or commentary outside of the spoken script.
"""
    
    print("Requesting summary from Gemini...")
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
    print("Generating audio with Gemini TTS (Charon voice)...")
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

    state_file = os.path.join(os.path.dirname(__file__), "last_economist_intelligence_guid.txt")
    episode_title, mp3_url, current_guid = fetch_latest()
    
    if not episode_title or not mp3_url:
        print("Failed to fetch latest episode.")
        return

    # Check if this podcast has already been processed
    if current_guid and os.path.exists(state_file):
        with open(state_file, "r") as f:
            last_guid = f.read().strip()
        if current_guid == last_guid:
            print("No new The Intelligence episode detected. Exiting.")
            return

    print(f"Latest Episode: {episode_title}")
    
    local_audio = os.path.join(os.path.dirname(__file__), "temp_economist_intelligence.mp3")
    download_file(mp3_url, local_audio)
    
    client = genai.Client()
    
    summary_text = generate_summary_from_audio(client, local_audio)
    
    display_title = f"The Economist The Intelligence: {episode_title}"
    full_text_for_feed = f"**{display_title}**\n\n" + summary_text
    
    import datetime
    date_str = datetime.datetime.now().strftime("%B %-d, %Y")
    spoken_text = f"This is The Economist, The Intelligence. Episode of {date_str}. " + summary_text.replace("**", "")
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
        
    # Update state file
    if current_guid:
        with open(state_file, "w") as f:
            f.write(current_guid)
            
    print(f"Publishing episode '{display_title}' to GitHub Pages podcast feed...")
    github_podcast.publish_episode(display_title, full_text_for_feed, mp3_bytes)
    
    print("Done!")

if __name__ == "__main__":
    main()
