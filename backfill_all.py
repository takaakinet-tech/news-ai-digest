import os
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
import subprocess
from google import genai
from google.genai import types

sys.path.append("scripts")
import github_podcast
from dotenv import load_dotenv

load_dotenv()

# Mock git commands to avoid pushing 27 times
original_run = subprocess.run
def mock_run(args, **kwargs):
    if args and args[0] == "git":
        return
    return original_run(args, **kwargs)
subprocess.run = mock_run

PODCASTS = [
    {"publisher": "", "title": "The AI Breakdown", "rss_url": "https://feeds.libsyn.com/468519/rss"},
    {"publisher": "New York Times", "title": "Hard Fork", "rss_url": "https://feeds.simplecast.com/83p5Hn2n"},
    {"publisher": "The Economist", "title": "The Intelligence", "rss_url": "https://feeds.acast.com/public/shows/the-intelligence-from-the-economist"},
    {"publisher": "Wall Street Journal", "title": "The Journal", "rss_url": "https://feeds.megaphone.fm/wsjthejournal"},
    {"publisher": "Financial Times", "title": "FT News Briefing", "rss_url": "https://feeds.acast.com/public/shows/ft-news-briefing"},
    {"publisher": "Bloomberg", "title": "The Big Take", "rss_url": "https://feeds.megaphone.fm/BLM2201990264"},
    {"publisher": "Washington Post", "title": "Post Reports", "rss_url": "https://feeds.simplecast.com/83p5H1Vf"}
]

def download_file(url, local_filename):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as response, open(local_filename, 'wb') as out_file:
        data = response.read()
        out_file.write(data)

def generate_summary(client, podcast_title, audio_file_path):
    print(f"Uploading {podcast_title} to Gemini...")
    uploaded_file = client.files.upload(file=audio_file_path)
    prompt = f"""
You are an elite audio briefing announcer. Analyze the provided podcast audio from "{podcast_title}" and create a highly condensed, intellectually dense 3-4 minute briefing script in English.
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
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash-preview-tts',
            contents=[text],
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Charon")
                    )
                )
            )
        )
        for part in response.candidates[0].content.parts:
            if part.inline_data:
                return part.inline_data.data
    except Exception as e:
        print(f"TTS Failed: {e}")
    return None

client = genai.Client()

for p in PODCASTS:
    print(f"\n--- Backfilling: {p['title']} ---")
    try:
        req = urllib.request.Request(p["rss_url"], headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            xml_data = response.read()
        root = ET.fromstring(xml_data)
        items = root.findall('.//item')
        
        # Process older first so that they appear in chronological order (index 2, 1, 0)
        # index 2 = 3rd latest, index 1 = 2nd latest, index 0 = latest
        for item in reversed(items[:3]):
            ep_title = item.find('title').text
            enclosure = item.find('enclosure')
            mp3_url = enclosure.get('url') if enclosure is not None else None
            
            if not mp3_url:
                continue
                
            print(f"Processing: {ep_title}")
            local_audio = "temp_dl.mp3"
            download_file(mp3_url, local_audio)
            
            summary_text = generate_summary(client, p["title"], local_audio)
            
            display_title = f"{p['publisher'] + ' ' if p['publisher'] else ''}{p['title']}: {ep_title}"
            full_text_for_feed = f"**{display_title}**\n\n" + summary_text
            
            import datetime
            date_str = datetime.datetime.now().strftime("%B %-d, %Y")
            spoken_text = f"This is {p['publisher'] + ', ' if p['publisher'] else ''}{p['title']}. Episode of {date_str}. " + summary_text.replace("**", "")
            
            wav_bytes = generate_audio(client, spoken_text)
            if not wav_bytes:
                continue
                
            timestamp = int(time.time())
            wav_filename = f"temp_{timestamp}.wav"
            mp3_filename = f"temp_{timestamp}.mp3"
            
            with open(wav_filename, "wb") as f:
                f.write(wav_bytes)
                
            original_run([
                "ffmpeg", "-y", "-f", "s16le", "-ar", "24000", "-ac", "1", 
                "-i", wav_filename, "-filter:a", "atempo=1.25", "-b:a", "128k", mp3_filename
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            with open(mp3_filename, "rb") as f:
                mp3_bytes = f.read()
                
            os.remove(wav_filename)
            os.remove(mp3_filename)
            if os.path.exists(local_audio):
                os.remove(local_audio)
            
            github_podcast.publish_episode(display_title, full_text_for_feed, mp3_bytes)
            print(f"Saved episode: {display_title}")
            
    except Exception as e:
        print(f"Error processing {p['title']}: {e}")

# Now actually commit and push everything once at the end!
print("Pushing to GitHub...")
original_run = subprocess.run  # restore
original_run(["git", "add", "."])
original_run(["git", "commit", "-m", "Backfill 3 past episodes for all 9 new podcasts"])
original_run(["git", "push"])
print("ALL DONE!")
