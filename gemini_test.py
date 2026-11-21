import os
import time
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

VIDEO_FOLDER = "./my_reels"

def analyze_reel_and_generate_caption(video_path: str, focus_topic: str = None) -> str:
    """
    Uploads a Reel video to Gemini, reviews its content, 
    and generates an optimized caption with hooks and hashtags.
    """
    # Initialize the standard GenAI client
    client = genai.Client(http_options={'api_version': 'v1beta'})
    
    print(f"Uploading {video_path} to Gemini File API...")
    # Stage the video file on Gemini servers
    video_file = client.files.upload(file=video_path)
    print(f"File uploaded. State: {video_file.state}")

    # Videos require a brief processing window before inference
    while video_file.state.name == "PROCESSING":
        print("Waiting for video processing to complete...")
        time.sleep(5)
        video_file = client.files.get(name=video_file.name)

    if video_file.state.name == "FAILED":
        raise ValueError(f"Video processing failed on Gemini server: {video_file.error.message}")

    print("Video is active and ready for analysis.")

    # Craft structured instructions for the review task
    system_instruction = (
        "You are an expert social media strategist and copywriter specializing in Instagram Reels. "
        "Analyze the uploaded video's visual action, audio, pacing, and emotional tone. "
        "Provide a concise summary analysis of the video, followed by 3 distinct caption options "
        "(e.g., Short/Punchy, Storytelling, and Engagement/Question-based) matching the vibe. "
        "Include natural hook spacing, appropriate emojis, and relevant trending hashtags."
        "if video is from a movie or TV show, include the title and any relevant character names in the captions. "
        "provide one title that can be put at the top of the reel. it should be short and catchy. "
        "only provide one caption so that it can be used directly for posting. "
        "provide the output in json format with keys: 'summary', 'caption' and don't include stars or other markdown."
    )

    prompt = "Review this video clip completely. "
    if focus_topic:
        prompt += f"Ensure the caption hooks specifically tie back into the concept of: '{focus_topic}'."

    try:
        print("Analyzing video and generating copy...")
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[video_file, prompt],
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.7, # Adds healthy creative variation to the copy
            )
        )
        
        return response.text

    finally:
        # Best Practice: Always clean up staged large media assets from your cloud workspace
        print("Cleaning up file from Gemini servers...")
        client.files.delete(name=video_file.name)
        print("Cleanup complete.")

# # --- Execution Example ---
# if __name__ == "__main__":
#     # Path to your local mp4/mov Reel file
#     my_reel = os.path.join(VIDEO_FOLDER, os.listdir(VIDEO_FOLDER)[0]) if os.listdir(VIDEO_FOLDER) else None

#     if os.path.exists(my_reel):
#         caption_suite = analyze_reel_and_generate_caption(
#             video_path=my_reel
#         )
#         print("\n=== GEMINI ANALYSIS & CAPTIONS ===\n")
#         print(caption_suite)
#     else:
#         print(f"Please place a valid video file at: {my_reel}")
