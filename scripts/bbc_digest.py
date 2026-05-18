import sys, os
try:
    sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)).split(".agents")[0], ".agents"))
    import cost_guard
except ImportError:
    pass
import os
import urllib.request
import subprocess
import xml.etree.ElementTree as ET
import requests
from google import genai
from google.genai import types
import time
from dotenv import load_dotenv
import github_podcast

# Load environment variables if .env exists
load_dotenv()

# Discord Webhook URL
WEBHOOK_URL = "https://discord.com/api/webhooks/1475408294221713498/jBeijwwf6LHM7OyyhhGaMGqo8eY6OjXyHENg1kMXHaSoSI8vDKFQsodPPxgCBTSnexrr"

def fetch_bbc_rss():
    print("Fetching BBC World News RSS...")
    url = "http://feeds.bbci.co.uk/news/world/rss.xml"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    response = urllib.request.urlopen(req)
    xml_data = response.read()
    root = ET.fromstring(xml_data)
    
    items = []
    for item in root.findall('./channel/item'):
        title = item.find('title').text if item.find('title') is not None else ""
        desc = item.find('description').text if item.find('description') is not None else ""
        items.append(f"Title: {title}\nDescription: {desc}")
    return items

def fetch_bbc_podcast_info():
    print("Fetching actual BBC Global News Podcast info...")
    try:
        url = "https://podcasts.files.bbci.co.uk/p02nq0gn.rss"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        response = urllib.request.urlopen(req)
        xml_data = response.read()
        root = ET.fromstring(xml_data)
        latest_item = root.find('./channel/item')
        if latest_item is not None and latest_item.find('title') is not None:
            title = latest_item.find('title').text.strip()
            guid = latest_item.find('guid').text.strip() if latest_item.find('guid') is not None else ""
            return title, guid
    except Exception as e:
        print(f"Failed to fetch podcast info: {e}")
    return "Global News Podcast", ""

def generate_text_summary(client, news_items):
    print("Generating comprehensive text summary with Gemini...")
    prompt = """
You are a professional news anchor delivering a rapid-fire, high-density morning digest.
I will provide you with the raw news items from the latest BBC World News RSS feed.

Your instructions:
1. STRICT GROUNDING: You MUST ONLY use the news items provided in the raw text below. Do NOT invent, hallucinate, or include any outside news events, regardless of how important they are. If it's not in the text below, it does not exist.
2. FILTER AGGRESSIVELY: Discard any news related to entertainment, soft culture, obituaries, sports, or minor regional events from the provided text. Keep ONLY major global geopolitical, economic, and systemic news from the provided text.
3. INDIVIDUAL SUMMARIZATION: Succinctly summarize each piece of news exactly as it is presented. Do not incorporate or lump them together into crudely summarized takeaway messages. Give each chunk and each piece individually, providing the summarized details thereof.
4. MAINTAIN ORDER: You must maintain the original order of the news items.
5. Format each kept item as a numbered list with the headline in bold, followed by the concise summary.
6. Do not add any conversational intros or outros.

Here is the raw news feed. YOU MUST NOT DEVIATE FROM THIS:
""" + "\n\n".join(news_items)

    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt
    )
    return response.text

def generate_audio(client, text_summary):
    print("Generating audio with Gemini TTS (Charon voice)...")
    import datetime
    # Add a brief intro for the audio version
    date_str = datetime.datetime.now().strftime("%B %-d, %Y")
    spoken_text = f"This is BBC World News. Episode of {date_str}. " + text_summary.replace("**", "")
    
    response = client.models.generate_content(
        model='gemini-2.5-flash-preview-tts',
        contents=spoken_text,
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
    
    audio_bytes = None
    if hasattr(response, 'generated_responses') and response.generated_responses and hasattr(response.generated_responses[0], 'audio') and response.generated_responses[0].audio:
        audio_bytes = response.generated_responses[0].audio.content
    elif hasattr(response, 'candidates') and response.candidates and hasattr(response.candidates[0], 'content') and hasattr(response.candidates[0].content, 'parts'):
        for part in response.candidates[0].content.parts:
             if hasattr(part, 'inline_data') and part.inline_data:
                 audio_bytes = part.inline_data.data
                 break
    
    if not audio_bytes:
        print("Failed to generate audio bytes from response.")
        return None
        
    return audio_bytes



import datetime

def main():
    if not os.environ.get("GEMINI_API_KEY"):
        print("Error: GEMINI_API_KEY environment variable not set.")
        return

    state_file = os.path.join(os.path.dirname(__file__), "last_podcast_guid.txt")
    podcast_title, current_guid = fetch_bbc_podcast_info()
    
    # Check if this podcast has already been processed
    if current_guid and os.path.exists(state_file):
        with open(state_file, "r") as f:
            last_guid = f.read().strip()
        if current_guid == last_guid:
            print("No new podcast episode detected. Exiting.")
            return

    client = genai.Client()
    news_items = fetch_bbc_rss()
    if not news_items:
        print("No news items found.")
        return
        
    text_summary = generate_text_summary(client, news_items)
    
    # Add date, year, and time to the beginning of the text
    now = datetime.datetime.now()
    date_str = now.strftime("%A, %B %d, %Y at %I:%M %p")
    header = f"**BBC World News Digest — {date_str}**\n**Podcast Episode:** {podcast_title}\n\n"
    text_summary = header + text_summary
    
    # Generate audio
    wav_bytes = generate_audio(client, text_summary)
    
    # Convert to MP3
    timestamp = int(time.time())
    wav_filename = f"temp_{timestamp}.wav"
    mp3_filename = f"temp_{timestamp}.mp3"
    with open(wav_filename, "wb") as f:
        f.write(wav_bytes)
        
    print("Compressing and speeding up audio to MP3...")
    subprocess.run(["ffmpeg", "-y", "-f", "s16le", "-ar", "24000", "-ac", "1", "-i", wav_filename, "-filter:a", "atempo=1.25", "-b:a", "128k", mp3_filename], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    mp3_bytes = None
    if os.path.exists(mp3_filename):
        with open(mp3_filename, "rb") as f:
            mp3_bytes = f.read()
        os.remove(wav_filename)
        os.remove(mp3_filename)
    else:
        print("FFmpeg failed!")
        mp3_bytes = wav_bytes # fallback

    # Send to discord
    # (Discord integration has been removed as per user request)
    # Save the new guid so we don't process it again
    if current_guid:
        with open(state_file, "w") as f:
            f.write(current_guid)
            
    # Publish to GitHub Podcast feed
    print("Publishing episode to GitHub Pages podcast feed...")
    display_title = f"BBC World News Digest: {podcast_title}"
    github_podcast.publish_episode(display_title, text_summary, mp3_bytes)
            
if __name__ == "__main__":
    main()
