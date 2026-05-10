import os
import sys
import time
import requests
import feedparser
import subprocess
from google import genai
from google.genai import types
from dotenv import load_dotenv

sys.path.append("scripts")
import github_podcast

load_dotenv()

PODCASTS = [
    # Original
    {"publisher": "BBC", "title": "World News Digest", "rss_url": "https://podcasts.files.bbci.co.uk/p02nq0gn.rss", "slug": "bbc_news"},
    {"publisher": "New York Times", "title": "The Daily", "rss_url": "https://feeds.simplecast.com/54nAGcIl", "slug": "nyt_daily"},
    {"publisher": "Komugiko", "title": "令和メガネ合戦", "rss_url": "https://anchor.fm/s/2b260e04/podcast/rss", "slug": "komugiko"},
    # New
    {"publisher": "", "title": "The AI Breakdown", "rss_url": "https://feeds.libsyn.com/468519/rss", "slug": "ai_breakdown"},
    {"publisher": "New York Times", "title": "Hard Fork", "rss_url": "https://feeds.simplecast.com/l2i9YnTd", "slug": "hard_fork"},
    {"publisher": "The Economist", "title": "The Intelligence", "rss_url": "https://feeds.acast.com/public/shows/d556eb54-6160-4c85-95f4-47d9f5216c49", "slug": "the_intelligence"},
    {"publisher": "Wall Street Journal", "title": "The Journal", "rss_url": "https://feeds.megaphone.fm/WSJ4693364973", "slug": "the_journal"},
    {"publisher": "Financial Times", "title": "FT News Briefing", "rss_url": "https://feeds.acast.com/public/shows/73fe3ede-5c5c-4850-96a8-30db8dbae8bf", "slug": "ft_news"},
    {"publisher": "Bloomberg", "title": "The Big Take", "rss_url": "https://www.omnycontent.com/d/playlist/e73c998e-6e60-432f-8610-ae210140c5b1/825d4e29-b616-46f4-afd7-ae2b0013005c/8b1dd624-a026-43e9-8b57-ae2b00130066/podcast.rss", "slug": "bloomberg_take"},
    {"publisher": "Harvard Business Review", "title": "Cold Call", "rss_url": "http://feeds.harvardbusiness.org/harvardbusiness/cold-call", "slug": "hbr_coldcall"},
    {"publisher": "Washington Post", "title": "Post Reports", "rss_url": "https://podcast.posttv.com/itunes/post-reports.xml", "slug": "wapo_post"}
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/rss+xml, application/xml, text/xml, */*'
}

client = genai.Client()

def get_last_guid(slug):
    state_file = f"state/last_{slug}_guid.txt"
    if os.path.exists(state_file):
        with open(state_file, "r") as f:
            return f.read().strip()
    return None

def set_last_guid(slug, guid):
    os.makedirs("state", exist_ok=True)
    with open(f"state/last_{slug}_guid.txt", "w") as f:
        f.write(guid)

for p in PODCASTS:
    try:
        print(f"Checking {p['title']}...")
        resp = requests.get(p["rss_url"], headers=HEADERS, timeout=15)
        resp.raise_for_status()
        
        feed = feedparser.parse(resp.content)
        if not feed.entries:
            continue
            
        latest_item = feed.entries[0]
        latest_guid = latest_item.id if hasattr(latest_item, 'id') else latest_item.link
        
        last_guid = get_last_guid(p["slug"])
        if last_guid == latest_guid:
            print(f"No new episodes for {p['title']}")
            continue
            
        print(f"New episode found for {p['title']}: {latest_item.title}")
        
        mp3_url = None
        for link in latest_item.links:
            if link.rel == 'enclosure' and 'audio' in link.type:
                mp3_url = link.href
                break
                
        if not mp3_url:
            continue
            
        local_audio = f"temp_{p['slug']}.mp3"
        r = requests.get(mp3_url, headers=HEADERS, stream=True, allow_redirects=True, timeout=30)
        with open(local_audio, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
                
        # Generate Summary
        uploaded = client.files.upload(file=local_audio)
        prompt = f"""You are an elite audio briefing announcer. Analyze this episode of {p['title']} and create a 3-4 minute briefing script in English.
Structure logically into: 1. The Core Thesis, 2. The 3 Key Insights, 3. The 'So What?', 4. The Golden Quote.
Output ONLY in Scale Markdown format (plain text, NO markdown symbols)."""
        
        sum_resp = client.models.generate_content(model='gemini-2.5-flash', contents=[uploaded, prompt])
        summary = sum_resp.text
        try: client.files.delete(name=uploaded.name)
        except: pass
        
        display_title = f"{p['publisher'] + ' ' if p['publisher'] else ''}{p['title']}: {latest_item.title}"
        full_text = f"**{display_title}**\n\n" + summary
        
        import datetime
        date_str = datetime.datetime.now().strftime("%B %-d, %Y")
        spoken = f"This is {p['publisher'] + ', ' if p['publisher'] else ''}{p['title']}. Episode of {date_str}. " + summary.replace("**", "")
        
        # Generate TTS
        audio_resp = client.models.generate_content(
            model='gemini-2.5-flash-preview-tts',
            contents=[spoken],
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Charon")
                ))
            )
        )
        wav_bytes = audio_resp.candidates[0].content.parts[0].inline_data.data
        
        wav_fn = f"temp_{int(time.time())}.wav"
        mp3_fn = f"temp_{int(time.time())}.mp3"
        with open(wav_fn, "wb") as f: f.write(wav_bytes)
        
        subprocess.run(["/opt/homebrew/bin/ffmpeg", "-y", "-f", "s16le", "-ar", "24000", "-ac", "1", "-i", wav_fn, "-filter:a", "atempo=1.25", "-b:a", "128k", mp3_fn], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        with open(mp3_fn, "rb") as f: mp3_bytes = f.read()
        
        os.remove(wav_fn)
        os.remove(mp3_fn)
        os.remove(local_audio)
        
        # We MUST save the state before pushing, in case push fails or takes long
        set_last_guid(p["slug"], latest_guid)
        
        github_podcast.publish_episode(display_title, full_text, mp3_bytes)
        print(f"Published {display_title}!")
        
    except Exception as e:
        print(f"Error checking {p['title']}: {e}")
