import os
import time
import subprocess
from xml.etree import ElementTree as ET
from xml.dom import minidom
import email.utils

REPO_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
EPISODES_DIR = os.path.join(REPO_DIR, "episodes")
RSS_FILE = os.path.join(REPO_DIR, "rss.xml")
BASE_URL = "https://takaakinet-tech.github.io/news-ai-digest"

def init_rss():
    rss = ET.Element("rss", version="2.0", attrib={"xmlns:itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "News AI Digest"
    ET.SubElement(channel, "link").text = BASE_URL
    ET.SubElement(channel, "description").text = "Ultra-fast, AI-summarized global news updates."
    ET.SubElement(channel, "language").text = "en-us"
    itunes_author = ET.SubElement(channel, "itunes:author")
    itunes_author.text = "Antigravity AI"
    itunes_image = ET.SubElement(channel, "itunes:image", href=f"{BASE_URL}/cover.png")
    return rss, channel

def publish_episode(podcast_title, text_summary, mp3_bytes):
    if not os.path.exists(EPISODES_DIR):
        os.makedirs(EPISODES_DIR)
        
    timestamp = int(time.time())
    filename = f"episode_{timestamp}.mp3"
    filepath = os.path.join(EPISODES_DIR, filename)
    
    with open(filepath, "wb") as f:
        f.write(mp3_bytes)
        
    audio_size = os.path.getsize(filepath)
    audio_url = f"{BASE_URL}/episodes/{filename}"
    
    if os.path.exists(RSS_FILE):
        tree = ET.parse(RSS_FILE)
        rss = tree.getroot()
        channel = rss.find("channel")
    else:
        rss, channel = init_rss()
        
    item = ET.Element("item")
    ET.SubElement(item, "title").text = podcast_title
    ET.SubElement(item, "itunes:title").text = podcast_title
    
    clean_desc = text_summary.replace("**", "")
    ET.SubElement(item, "description").text = clean_desc
    
    pub_date = email.utils.formatdate(time.time(), localtime=False)
    ET.SubElement(item, "pubDate").text = pub_date
    
    ET.SubElement(item, "enclosure", url=audio_url, length=str(audio_size), type="audio/mpeg")
    ET.SubElement(item, "guid").text = audio_url
    
    items = channel.findall("item")
    for old_item in items:
        channel.remove(old_item)
    channel.append(item)
    for old_item in items:
        channel.append(old_item)
        
    items = channel.findall("item")
    if len(items) > 50:
        for old_item in items[50:]:
            channel.remove(old_item)
            
    xmlstr = minidom.parseString(ET.tostring(rss)).toprettyxml(indent="  ")
    xmlstr = '\n'.join([line for line in xmlstr.split('\n') if line.strip()])
    
    with open(RSS_FILE, "w") as f:
        f.write(xmlstr)
        
    subprocess.run(["git", "config", "--global", "user.name", "github-actions[bot]"], cwd=REPO_DIR)
    subprocess.run(["git", "config", "--global", "user.email", "github-actions[bot]@users.noreply.github.com"], cwd=REPO_DIR)
    subprocess.run(["git", "add", "."], cwd=REPO_DIR)
    subprocess.run(["git", "commit", "-m", f"Add episode: {podcast_title}"], cwd=REPO_DIR)
    subprocess.run(["git", "push"], cwd=REPO_DIR)
    print(f"Published to GitHub Actions! URL: {audio_url}")
