"""Optional Gemini visual scene assessment. Never bypasses manual review."""
import argparse
import base64
import json
import os
import pathlib
import subprocess
import urllib.request

def frames(video, start, end, count=4):
    images=[]
    for i in range(count):
        t=start+(end-start)*(i+0.5)/count
        p=subprocess.run(["ffmpeg","-v","error","-ss",str(t),"-i",str(video),"-frames:v","1","-vf","scale=480:-2","-f","image2pipe","-vcodec","mjpeg","-"],capture_output=True,check=True)
        images.append(base64.b64encode(p.stdout).decode())
    return images

def assess(video, start, end, key, model):
    prompt="""You are a rigorous gaming Shorts editor. Assess ONLY what the four sampled frames actually show, not implied action or video title. These still frames cannot prove dialogue, audio quality, exact game title, complete narrative or whether a moment is exciting in motion. Output JSON with keys: observed_visuals (array of factual observations), possible_hook (string), mobile_crop_risk (low/medium/high), uncertainty (string), requires_full_video_review (true). Never give a definitive 100-point editorial score or invented dialogue."""
    parts=[{"text":prompt}]
    for encoded in frames(video,start,end):
        parts.append({"inline_data":{"mime_type":"image/jpeg","data":encoded}})
    body=json.dumps({"contents":[{"parts":parts}],"generationConfig":{"responseMimeType":"application/json","temperature":0.1}}).encode()
    url="https://generativelanguage.googleapis.com/v1beta/models/"+model+":generateContent"
    req=urllib.request.Request(url,data=body,headers={"Content-Type":"application/json","x-goog-api-key":key},method="POST")
    with urllib.request.urlopen(req,timeout=90) as response:
        data=json.load(response)
    text=data["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--output",default="output")
    p.add_argument("--model",default="gemini-2.5-flash")
    args=p.parse_args()
    root=pathlib.Path(args.output)
    manifest_path=root/"manifest.json"
    manifest=json.loads(manifest_path.read_text())
    key=os.getenv("GEMINI_API_KEY")
    if not key:
        manifest["semantic_status"]="NOT_RUN_MISSING_API_KEY"
    else:
        source=next((p for p in root.glob("vod.*") if p.suffix in {".mp4",".mkv",".webm",".mov"}),None)
        if source is None:
            manifest["semantic_status"]="NOT_RUN_MISSING_SOURCE"
        else:
            failures=0
            for clip in manifest.get("clips",[]):
                try:
                    clip["visual_assessment"]=assess(source,clip["start"],clip["end"],key,args.model)
                    clip["semantic_status"]="PARTIAL_FRAMES_ONLY_NEEDS_FULL_REVIEW"
                except Exception as e:
                    failures+=1
                    clip["semantic_status"]="FAILED"
                    clip["semantic_error"]=type(e).__name__
            manifest["semantic_status"]="PARTIAL_REVIEW" if not failures else "PARTIAL_FAILURE"
    manifest["publishing_allowed"]=False
    manifest_path.write_text(json.dumps(manifest,indent=2))
    print(manifest["semantic_status"])

if __name__=="__main__":
    main()
