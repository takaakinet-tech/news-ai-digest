import os
import sys
import time
import requests
import feedparser
import subprocess
import xml.etree.ElementTree as ET
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
    {"publisher": "Komugiko", "title": "令和メガネ合戦", "rss_url": "https://feeds.megaphone.fm/TBS7609676437", "slug": "komugiko"},
    # New
    {"publisher": "", "title": "The AI Breakdown", "rss_url": "https://feeds.libsyn.com/468519/rss", "slug": "ai_breakdown"},
    {"publisher": "New York Times", "title": "Hard Fork", "rss_url": "https://feeds.simplecast.com/l2i9YnTd", "slug": "hard_fork"},
    {"publisher": "The Economist", "title": "The Intelligence", "rss_url": "https://feeds.acast.com/public/shows/d556eb54-6160-4c85-95f4-47d9f5216c49", "slug": "the_intelligence"},
    {"publisher": "Wall Street Journal", "title": "The Journal", "rss_url": "https://feeds.megaphone.fm/WSJ4693364973", "slug": "the_journal"},
    {"publisher": "Financial Times", "title": "FT News Briefing", "rss_url": "https://feeds.acast.com/public/shows/73fe3ede-5c5c-4850-96a8-30db8dbae8bf", "slug": "ft_news"},
    {"publisher": "Bloomberg", "title": "The Big Take", "rss_url": "https://www.omnycontent.com/d/playlist/e73c998e-6e60-432f-8610-ae210140c5b1/825d4e29-b616-46f4-afd7-ae2b0013005c/8b1dd624-a026-43e9-8b57-ae2b00130066/podcast.rss", "slug": "bloomberg_take"},
    {"publisher": "Washington Post", "title": "Post Reports", "rss_url": "https://podcast.posttv.com/itunes/post-reports.xml", "slug": "wapo_post"}
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/rss+xml, application/xml, text/xml, */*'
}

client = genai.Client()

def get_processed_titles():
    processed = set()
    if os.path.exists("rss.xml"):
        tree = ET.parse("rss.xml")
        root = tree.getroot()
        for item in root.findall('.//item'):
            title_node = item.find('title')
            if title_node is not None and title_node.text:
                processed.add(title_node.text)
    return processed

def process_unstreamlined_podcasts(limit=10):
    processed_titles = get_processed_titles()
    processed_count = 0
    
    for p in PODCASTS:
        if processed_count >= limit:
            break
            
        print(f"Checking {p['title']}...")
        try:
            resp = requests.get(p["rss_url"], headers=HEADERS, timeout=15)
            resp.raise_for_status()
            
            feed = feedparser.parse(resp.content)
            if not feed.entries:
                continue
                
            # Find the first entry that is NOT processed
            new_entry = None
            for entry in feed.entries:
                display_title = f"{p['publisher'] + ' ' if p['publisher'] else ''}{p['title']}: {entry.title}"
                if display_title not in processed_titles:
                    # Also skip Komugiko older than 14 days
                    if p["slug"] == "komugiko" and hasattr(entry, 'published_parsed') and entry.published_parsed:
                        import datetime
                        pub_dt = datetime.datetime(*entry.published_parsed[:6])
                        if (datetime.datetime.utcnow() - pub_dt).days > 14:
                            print(f"Skipping old Komugiko episode: {entry.title}")
                            continue
                    new_entry = entry
                    break
                    
            if not new_entry:
                print(f"No un-streamlined episodes found for {p['title']}")
                continue
                
            display_title = f"{p['publisher'] + ' ' if p['publisher'] else ''}{p['title']}: {new_entry.title}"
            print(f"Found un-streamlined episode: {display_title}")
            
            mp3_url = None
            for link in new_entry.links:
                if link.rel == 'enclosure' and 'audio' in link.type:
                    mp3_url = link.href
                    break
            
            if not mp3_url:
                continue
                
            local_audio = f"temp_{p['slug']}.mp3"
            print(f"Downloading {mp3_url}...")
            r = requests.get(mp3_url, headers=HEADERS, stream=True, allow_redirects=True, timeout=30)
            with open(local_audio, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
                    
            print(f"Uploading to Gemini...")
            uploaded = client.files.upload(file=local_audio)
            
            news_slugs = ["bbc_news", "the_journal", "the_intelligence", "ft_news", "bloomberg_take", "wapo_post", "ai_breakdown"]
            story_slugs = ["nyt_daily", "hard_fork", "hbr_coldcall", "komugiko"]
            
            if p["slug"] == "komugiko":
                prompt = f"""あなたはエリート・オーディオブリーフィング・アナウンサーです。提供されたポッドキャスト音声（「{p['title']}」）を分析し、内容の密度が極めて高い3〜4分間の日本語ブリーフィング・スクリプトを作成してください。
【重要】
1. 絶対に英語など他の言語に翻訳しないでください。完全に日本語で出力すること。
2. ドライな時系列の要約ではなく、記憶に粘り付く名言やエピソード、モチベーションを高めるストーリーテリング、特別な洞察（インサイト）の抽出に特化してください。
3. 出力は「Scale Markdown」形式（記号を含まない純粋なテキスト）のみ。"""
            elif p["slug"] in story_slugs:
                prompt = f"""You are an elite audio briefing announcer. Analyze this episode of "{p['title']}" and create an intellectually dense 3-4 minute briefing script in English.
1. NO DRY SUMMARIES: Do NOT dryly present summarized chronological pieces or forcibly structure it into key takeaways.
2. FOCUS ON NARRATIVE IMPACT: Extract "made-to-stick" memorable quotes, engaging storytelling elements, and special implied insights.
3. NO MARKDOWN: Output ONLY in "Scale Markdown" format (plain text, NO markdown symbols). Ensure it reads naturally for TTS."""
            else:
                prompt = f"""You are an elite audio briefing announcer. Analyze this episode of "{p['title']}" and create a highly condensed 3-4 minute briefing script in English.
1. INDIVIDUAL SUMMARIZATION: Succinctly summarize each piece of news exactly as it is presented.
2. NO LUMPING: Do NOT incorporate or lump the stories together into crudely summarized takeaway messages.
3. MAINTAIN ORDER: Maintain the original chronological order of the news items.
4. NO MARKDOWN: Output ONLY in "Scale Markdown" format (plain text, NO markdown symbols). Ensure it reads naturally for TTS."""
            
            print("Generating text summary...")
            sum_resp = client.models.generate_content(model='gemini-2.5-flash', contents=[uploaded, prompt])
            summary = sum_resp.text
            try: client.files.delete(name=uploaded.name)
            except: pass
            
            full_text = f"**{display_title}**\n\n" + summary
            
            import datetime
            date_str = datetime.datetime.now().strftime("%B %-d, %Y")
            
            if p["slug"] == "komugiko":
                spoken = summary.replace("**", "")
            else:
                spoken = f"This is {p['publisher'] + ', ' if p['publisher'] else ''}{p['title']}. Episode of {date_str}. " + summary.replace("**", "")
            
            print("Generating TTS audio...")
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
            
            subprocess.run(["ffmpeg", "-y", "-f", "s16le", "-ar", "24000", "-ac", "1", "-i", wav_fn, "-filter:a", "atempo=1.25", "-b:a", "128k", mp3_fn], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            with open(mp3_fn, "rb") as f: mp3_bytes = f.read()
            
            os.remove(wav_fn)
            os.remove(mp3_fn)
            os.remove(local_audio)
            
            print(f"Publishing to feed...")
            github_podcast.publish_episode(display_title, full_text, mp3_bytes)
            processed_titles.add(display_title)
            processed_count += 1
            print(f"Published {processed_count}/{limit}: {display_title}!")
            
            # Update state file just in case it was the latest episode
            latest_guid = feed.entries[0].id if hasattr(feed.entries[0], 'id') else feed.entries[0].link
            if new_entry.title == feed.entries[0].title:
                os.makedirs("state", exist_ok=True)
                with open(f"state/last_{p['slug']}_guid.txt", "w") as f:
                    f.write(latest_guid)
            
        except Exception as e:
            print(f"Error checking {p['title']}: {e}")

if __name__ == "__main__":
    process_unstreamlined_podcasts(10)
