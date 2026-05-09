import os
import sys
import time
import json
import subprocess
from google import genai
from google.genai import types

# Add parent directory to path to import github_podcast
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import github_podcast
from dotenv import load_dotenv

load_dotenv()

def process_book(pdf_path):
    print(f"Processing book: {pdf_path} (Chapter 4 onwards)")
    client = genai.Client()
    
    print("Uploading PDF to Gemini (this may take a minute for a full book)...")
    try:
        uploaded_file = client.files.upload(file=pdf_path)
        print(f"Uploaded as {uploaded_file.name}")
    except Exception as e:
        print(f"Upload failed: {e}")
        return
    
    prompt_outline = """
Analyze this book and provide a JSON list of its main chapters.
Return ONLY a valid JSON array of objects. Do not include markdown formatting or backticks.
Format:
[
  {"chapter_number": "1", "chapter_title": "Name of the Chapter"},
  ...
]
Limit to a maximum of 20 major sections.
"""
    print("Extracting chapter outline from the entire book...")
    try:
        outline_response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[uploaded_file, prompt_outline]
        )
    except Exception as e:
        print(f"Outline generation failed: {e}")
        return
        
    try:
        raw_json = outline_response.text.replace('```json', '').replace('```', '').strip()
        chapters = json.loads(raw_json)
        print(f"Successfully identified {len(chapters)} chapters.")
    except Exception as e:
        print("Failed to parse chapters JSON:", e)
        print("Raw response:", outline_response.text)
        return
        
    # Process from chapter 16 (index 15) onwards, since chapters 1-15 were successfully processed
    remaining_chapters = chapters[15:]
    print(f"\nWe will generate audio for the remaining {len(remaining_chapters)} chapters.")
    
    for ch in remaining_chapters:
        ch_title = f"Chapter {ch['chapter_number']}: {ch['chapter_title']}"
        print(f"\n--- Generating script for {ch_title} ---")
        
        prompt_script = f"""
You are an elite audio briefing announcer and master storyteller. Summarize "{ch_title}" from the provided book.
Create an engaging 3-4 minute briefing script in English that balances intellectual density with deep human emotion.
Do NOT simply provide a dry chronological summary. Structure the script logically into 4 sections:
1. **The Core Thesis:** State the absolute core point of this chapter.
2. **The 3 Key Insights:** Extract the three most critical insights or events from this chapter. Use transitional words like "First,", "Second,", and "Third,".
3. **The "Made to Stick" Drama:** Dedicate a significant portion of the script to a deeply human episode, an emotional rollercoaster (sorrow, shock, triumph) experienced by the characters, or a highly surprising fact. This section MUST be vivid and highly memorable, focusing on the intense human drama or the most shocking elements behind the facts.
4. **The "So What?":** Conclude by explaining the broader implications of this chapter.

Output the script ONLY in English and ONLY in "Scale Markdown" format (plain text, no markdown symbols like # or *). Ensure it reads naturally for an English TTS engine.
"""
        script_resp = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[uploaded_file, prompt_script]
        )
        script_text = script_resp.text
        
        print(f"Generating audio for {ch_title}...")
        try:
            audio_resp = client.models.generate_content(
                model='gemini-2.5-flash-preview-tts',
                contents=[f"This is an audio summary of Genius Makers, {ch_title}. " + script_text],
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
            continue
            
        if not wav_bytes:
            print("No audio generated.")
            continue
            
        timestamp = int(time.time())
        wav_filename = f"temp_{timestamp}.wav"
        mp3_filename = f"temp_{timestamp}.mp3"
        
        with open(wav_filename, "wb") as f:
            f.write(wav_bytes)
            
        print("Compressing MP3...")
        subprocess.run([
            "ffmpeg", "-y", "-f", "s16le", "-ar", "24000", "-ac", "1", 
            "-i", wav_filename, "-b:a", "128k", mp3_filename
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        with open(mp3_filename, "rb") as f:
            mp3_bytes = f.read()
            
        os.remove(wav_filename)
        os.remove(mp3_filename)
        
        display_title = f"{os.path.basename(pdf_path).replace('.pdf', '')}: {ch_title}"
        full_text_for_feed = f"**{display_title}**\n\n" + script_text
        
        print(f"Publishing {display_title} to Podcast Feed...")
        github_podcast.publish_episode(display_title, full_text_for_feed, mp3_bytes)
        
    try:
        client.files.delete(name=uploaded_file.name)
    except:
        pass
        
    print("\nBook processing complete!")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        process_book(sys.argv[1])
    else:
        print("Please provide a PDF path.")
