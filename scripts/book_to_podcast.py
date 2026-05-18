import sys, os
try:
    sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)).split(".agents")[0], ".agents"))
    import cost_guard
except ImportError:
    pass
import os
import sys
import time
import json
import subprocess
import fitz  # PyMuPDF
from google import genai
from google.genai import types

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import github_podcast
from dotenv import load_dotenv

load_dotenv()

def process_book(pdf_path):
    print(f"Processing book: {pdf_path} (Cost-Optimized Version)")
    client = genai.Client()
    
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"Failed to open PDF: {e}")
        return
        
    print("Uploading PDF to Gemini ONCE for chapter outline extraction...")
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
  {"chapter_number": "1", "chapter_title": "Name of the Chapter", "start_page_index": 15, "end_page_index": 35},
  ...
]
IMPORTANT: "start_page_index" and "end_page_index" must be the absolute 0-indexed page numbers in the PDF file where the chapter starts and ends.
Limit to a maximum of 20 major sections.
"""
    print("Extracting chapter outline and page ranges...")
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
        
    # We no longer need the full file stored in Google Cloud, delete it to save any potential storage fees.
    try:
        client.files.delete(name=uploaded_file.name)
        print("Deleted full PDF from Gemini to save costs.")
    except Exception as e:
        print("Warning: could not delete file:", e)
        
    demo_chapters = chapters[:3]
    print(f"\nFor this trial, we will generate audio for the first {len(demo_chapters)} chapters.")
    
    for ch in demo_chapters:
        ch_title = f"Chapter {ch['chapter_number']}: {ch.get('chapter_title', '')}"
        print(f"\n--- Generating script for {ch_title} ---")
        
        # EXTRACT JUST THIS CHAPTER'S TEXT LOCALLY (Massive Cost Saving)
        start_idx = ch.get("start_page_index", 0)
        end_idx = ch.get("end_page_index", len(doc) - 1)
        
        if start_idx < 0: start_idx = 0
        if end_idx >= len(doc): end_idx = len(doc) - 1
        if start_idx > end_idx: start_idx, end_idx = end_idx, start_idx
        
        chapter_text = ""
        for i in range(start_idx, end_idx + 1):
            page = doc.load_page(i)
            chapter_text += page.get_text() + "\n"
            
        if len(chapter_text.strip()) < 50:
            print(f"Skipping {ch_title} because extracted text is too short.")
            continue
            
        prompt_script = f"""
You are an elite narrator. Analyze the following text extracted from "{ch_title}".
Create an immersive, intellectually dense 3-4 minute narration script in English.

Your instructions are as follows:
1. IMMERSIVE NARRATION: Make the listener feel as if they are reading the chapters directly. Do NOT dryly summarize.
2. MEMORABLE QUOTES: Focus heavily on extracting "made-to-stick" memorable quotes from the chapter text.
3. INDEPENDENT CATEGORY: This is a book narration, so ignore typical news frameworks.
4. NO MARKDOWN: Output the script ONLY in English and ONLY in "Scale Markdown" format (plain text, no markdown symbols like `#` or `*`).

--- TEXT OF {ch_title} ---
{chapter_text}
"""
        try:
            script_resp = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt_script
            )
            script_text = script_resp.text
        except Exception as e:
            print("Failed to generate script:", e)
            continue
        
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
            "-i", wav_filename, "-filter:a", "atempo=1.25", "-b:a", "128k", mp3_filename
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        with open(mp3_filename, "rb") as f:
            mp3_bytes = f.read()
            
        os.remove(wav_filename)
        os.remove(mp3_filename)
        
        display_title = f"Genius Makers: {ch_title}"
        full_text_for_feed = f"**{display_title}**\n\n" + script_text
        
        print(f"Publishing {display_title} to Podcast Feed...")
        github_podcast.publish_episode(display_title, full_text_for_feed, mp3_bytes)
        
    print("\nBook processing complete!")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        process_book(sys.argv[1])
    else:
        print("Please provide a PDF path.")
