import os
import sys
import time
import requests
import feedparser
import subprocess
from google import genai
from google.genai import types
from dotenv import load_dotenv

# Load API key from .env
load_dotenv()
if not os.getenv("GEMINI_API_KEY"):
    print("Error: GEMINI_API_KEY not found in .env")
    sys.exit(1)

# Add scripts directory to path to import github_podcast
sys.path.append("scripts")
import github_podcast

# Override github_podcast.publish_episode temporarily so we don't push until the very end
original_run = subprocess.run
def mock_run(args, **kwargs):
    if args and args[0] == "git":
        return
    return original_run(args, **kwargs)
subprocess.run = mock_run

PODCASTS = [
    {"publisher": "New York Times", "title": "Hard Fork", "rss_url": "https://feeds.simplecast.com/l2i9YnTd"},
    {"publisher": "The Economist", "title": "The Intelligence", "rss_url": "https://feeds.acast.com/public/shows/d556eb54-6160-4c85-95f4-47d9f5216c49"},
    {"publisher": "Wall Street Journal", "title": "The Journal", "rss_url": "https://feeds.megaphone.fm/WSJ4693364973"},
    {"publisher": "Financial Times", "title": "FT News Briefing", "rss_url": "https://feeds.acast.com/public/shows/73fe3ede-5c5c-4850-96a8-30db8dbae8bf"},
    {"publisher": "Bloomberg", "title": "The Big Take", "rss_url": "https://www.omnycontent.com/d/playlist/e73c998e-6e60-432f-8610-ae210140c5b1/825d4e29-b616-46f4-afd7-ae2b0013005c/8b1dd624-a026-43e9-8b57-ae2b00130066/podcast.rss"},
    {"publisher": "Washington Post", "title": "Post Reports", "rss_url": "https://podcast.posttv.com/itunes/post-reports.xml"}
]
# Excluded 'The AI Breakdown' because it already succeeded earlier.

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/rss+xml, application/xml, text/xml, */*'
}

def download_file(url, local_filename):
    print(f"Downloading from {url}")
    # Allow redirects, use modern browser headers
    response = requests.get(url, headers=HEADERS, stream=True, allow_redirects=True, timeout=30)
    response.raise_for_status()
    with open(local_filename, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

def generate_summary(client, podcast_title, audio_file_path):
    print(f"Uploading {podcast_title} audio to Gemini...")
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
        # Use requests to fetch RSS, bypassing basic urllib blocks
        rss_resp = requests.get(p["rss_url"], headers=HEADERS, timeout=15)
        rss_resp.raise_for_status()
        
        feed = feedparser.parse(rss_resp.content)
        items = feed.entries
        
        # Process the latest 3 episodes, oldest to newest (chronological order)
        for item in reversed(items[:3]):
            ep_title = item.title
            mp3_url = None
            for link in item.links:
                if link.rel == 'enclosure' and 'audio' in link.type:
                    mp3_url = link.href
                    break
            
            if not mp3_url:
                print(f"No audio enclosure found for {ep_title}")
                continue
                
            print(f"Processing: {ep_title}")
            local_audio = "temp_dl.mp3"
            try:
                download_file(mp3_url, local_audio)
            except Exception as e:
                print(f"Failed to download audio for {ep_title}: {e}")
                continue
            
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

print("\nPushing to GitHub...")
subprocess.run = original_run  # restore git capability
original_run(["git", "add", "."])
original_run(["git", "commit", "-m", "Backfill remaining podcasts using requests"])
original_run(["git", "push", "origin", "main"])
print("ALL DONE!")
