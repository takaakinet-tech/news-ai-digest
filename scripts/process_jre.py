import sys, os
try:
    sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)).split(".agents")[0], ".agents"))
    import cost_guard
except ImportError:
    pass
import os
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from google import genai
from google.genai import types

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import github_podcast
from dotenv import load_dotenv

load_dotenv()

def get_jre_episode(ep_number_str):
    url = 'https://feeds.megaphone.fm/GLT1412515089'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as response:
        xml_data = response.read()

    root = ET.fromstring(xml_data)
    items = root.findall('.//item')
    
    for item in items:
        title = item.find('title').text
        if ep_number_str in title:
            enclosure = item.find('enclosure')
            mp3_url = enclosure.get('url') if enclosure is not None else None
            return title, mp3_url
    return None, None

def process_episode(ep_number_str):
    print(f"Searching for episode containing '{ep_number_str}'...")
    title, mp3_url = get_jre_episode(ep_number_str)
    
    if not mp3_url:
        print(f"Episode {ep_number_str} not found.")
        return
        
    print(f"Found: {title}")
    print(f"Downloading MP3 (this might take a minute): {mp3_url}")
    
    clean_ep_num = ep_number_str.replace('#', '')
    local_mp3 = f"jre_{clean_ep_num}.mp3"
    print(f"Saving locally as {local_mp3}")
    
    req = urllib.request.Request(mp3_url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as response, open(local_mp3, 'wb') as out_file:
        out_file.write(response.read())
    
    print("Uploading to Gemini 2.5 Flash (Processing 3 hours of audio)...")
    client = genai.Client()
    try:
        uploaded_file = client.files.upload(file=local_mp3)
        print(f"Uploaded as {uploaded_file.name}")
    except Exception as e:
        print(f"Upload failed: {e}")
        os.remove(local_mp3)
        return

    prompt_script = f"""
You are an elite audio briefing announcer and master storyteller. Summarize the Joe Rogan Experience "{title}" from the provided audio.
Create an engaging 3-4 minute briefing script in English that balances intellectual density with deep human emotion.
Do NOT simply provide a dry chronological summary. Structure the script logically into 4 sections:
1. **The Core Thesis:** State the absolute core point of this conversation.
2. **The 3 Key Insights:** Extract the three most critical insights, discoveries, or arguments from this episode. Use transitional words like "First,", "Second,", and "Third,".
3. **The "Made to Stick" Drama:** Dedicate a significant portion of the script to a deeply human episode, an emotional rollercoaster (sorrow, shock, triumph) experienced by the guest, or a highly surprising/shocking fact. This section MUST be vivid and highly memorable, focusing on the intense human drama or the most shocking elements behind the facts discussed.
4. **The "So What?":** Conclude by explaining the broader implications of this conversation for society or the listener.

Output the script ONLY in English and ONLY in "Scale Markdown" format (plain text, no markdown symbols like # or *). Ensure it reads naturally for an English TTS engine.
"""

    print("Generating Master Storyteller Script...")
    try:
        script_resp = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[uploaded_file, prompt_script]
        )
        script_text = script_resp.text
        print("Script generated successfully.")
    except Exception as e:
        print(f"Script generation failed: {e}")
        client.files.delete(name=uploaded_file.name)
        os.remove(local_mp3)
        return

    print("Generating TTS Audio...")
    try:
        audio_resp = client.models.generate_content(
            model='gemini-2.5-flash-preview-tts',
            contents=[f"This is an audio summary of the Joe Rogan Experience, {title}. " + script_text],
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Aoede")
                    )
                )
            )
        )
        wav_bytes = None
        for part in audio_resp.candidates[0].content.parts:
            if part.inline_data:
                wav_bytes = part.inline_data.data
                break
    except Exception as e:
        print("TTS Failed:", e)
        client.files.delete(name=uploaded_file.name)
        os.remove(local_mp3)
        return
        
    if not wav_bytes:
        print("No audio generated.")
        return
        
    timestamp = int(time.time())
    wav_filename = f"temp_{timestamp}.wav"
    out_mp3 = f"out_{timestamp}.mp3"
    
    with open(wav_filename, "wb") as f:
        f.write(wav_bytes)
        
    print("Compressing output to MP3 (1.0x speed)...")
    import subprocess
    subprocess.run([
        "/opt/homebrew/bin/ffmpeg", "-y", "-f", "s16le", "-ar", "24000", "-ac", "1", 
        "-i", wav_filename, "-b:a", "128k", out_mp3
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    with open(out_mp3, "rb") as f:
        final_mp3_bytes = f.read()
        
    os.remove(wav_filename)
    os.remove(out_mp3)
    os.remove(local_mp3)
    client.files.delete(name=uploaded_file.name)
    
    display_title = f"JRE Digest: {title}"
    full_text_for_feed = f"**{display_title}**\n\n" + script_text
    
    print(f"Publishing {display_title} to Podcast Feed...")
    github_podcast.publish_episode(display_title, full_text_for_feed, final_mp3_bytes)
    print("Done!")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        process_episode(sys.argv[1])
    else:
        print("Provide an episode number (e.g. #2496)")
