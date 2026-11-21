import os
import time
import shutil
import requests
import boto3
from dotenv import load_dotenv
from gemini_test import analyze_reel_and_generate_caption
import json
load_dotenv()

# --- CONFIGURATION ---
VIDEO_FOLDER = "./my_reels"
POSTED_FOLDER = "./posted_reels"

# Meta API Credentials
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
IG_ACCOUNT_ID = os.getenv("IG_ACCOUNT_ID")
GRAPH_API_VERSION = os.getenv("GRAPH_API_VERSION")

BUCKET_NAME = "reelsbucket"
s3_client = boto3.client(
    's3',
    endpoint_url=os.getenv("ENDPOINT_URL"),
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY")
)
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL") 

def upload_to_instagram():
    videos = [f for f in os.listdir(VIDEO_FOLDER) if f.endswith('.mp4')]
    if not videos:
        print("No videos left in the folder!")
        return

    next_video = sorted(videos)[0]
    local_path = os.path.join(VIDEO_FOLDER, next_video)
    try:
        gemini_response = analyze_reel_and_generate_caption(local_path)
        # Parse the JSON response to extract the caption
        response_data = json.loads(gemini_response)
        caption = response_data.get("caption", "#movies #reels #entertainment")
    except Exception as e:
        print("Couldn't generate caption:", e)
        caption = "#movies #reels #entertainment"

    print(f"Processing: {next_video}")

    try:
        # Step 1: Upload video to your temporary cloud storage
        print("Uploading video to temporary cloud storage...")
        s3_client.upload_file(local_path, BUCKET_NAME, next_video, ExtraArgs={'ContentType': 'video/mp4'})
        public_video_url = f"{PUBLIC_BASE_URL.rstrip('/')}/{'reelsbucket'}/{next_video}"
        print(f"Video uploaded to cloud storage. Public URL: {public_video_url}")

        # Step 2: Initialize the Reel container with Meta
        print("Initializing Reel container with Meta...")
        url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{IG_ACCOUNT_ID}/media"
        payload = {
            'media_type': 'REELS',
            'video_url': public_video_url,
            'caption': caption,
            'access_token': ACCESS_TOKEN
        }
        response = requests.post(url, data=payload).json()
        print("Container Creation Response:", response)
        container_id = response.get('id')
        
        if not container_id:
            print("Failed to create container:", response)
            return

        # Step 3: Wait for Meta to process the video (Reels take time to encode)
        print("Waiting for Meta to process the video...")
        status_url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{container_id}"
        params = {'fields': 'status_code,status', 'access_token': ACCESS_TOKEN}
        
        while True:
            status_res = requests.get(status_url, params=params).json()
            # print("Raw Status Response:", status_res)
            status = status_res.get('status_code')
            # print(f"Status: {status}")
            
            if status == "FINISHED":
                break
            elif status == "ERROR":
                print("Meta processing failed:", status_res)
                return
            else:
                print("Video is in queue, waiting...")
            
            time.sleep(10)

        # Step 4: Publish the Reel
        print("Publishing Reel...")
        publish_url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{IG_ACCOUNT_ID}/media_publish"
        publish_payload = {
            'creation_id': container_id,
            'access_token': ACCESS_TOKEN
        }
        publish_res = requests.post(publish_url, data=publish_payload).json()
        
        if 'id' in publish_res:
            print("Published successfully! ID:", publish_res.get('id'))
        else:
            print("Failed to publish:", publish_res)
            return

        # Step 5: Cleanup (Delete cloud file and move local file to archive)
        s3_client.delete_object(Bucket=BUCKET_NAME, Key=next_video)
        shutil.move(local_path, os.path.join(POSTED_FOLDER, next_video))

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        s3_client.delete_object(Bucket=BUCKET_NAME, Key=next_video)

if __name__ == "__main__":
    if not os.path.exists(POSTED_FOLDER):
        os.makedirs(POSTED_FOLDER)
    if not os.path.exists(VIDEO_FOLDER):
        os.makedirs(VIDEO_FOLDER)

    while True:
        upload_to_instagram()
        print("Waiting 2 hours for next upload...")
        time.sleep(7200)