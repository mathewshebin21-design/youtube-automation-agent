"""Fail-closed media QA and review gate for Twitch Shorts."""
import argparse
import json
import pathlib
import subprocess

def probe(path):
    result = subprocess.run(["ffprobe","-v","error","-show_streams","-show_format","-of","json",str(path)],capture_output=True,text=True,check=True)
    return json.loads(result.stdout)

def validate(path, expected_start=None, expected_end=None):
    failures=[]
    if not path.is_file() or path.stat().st_size==0:
        return {"status":"FAIL","failures":["missing_or_empty_media"]}
    try:
        info=probe(path)
        streams=info.get("streams",[])
        video=next((s for s in streams if s.get("codec_type")=="video"),None)
        audio=next((s for s in streams if s.get("codec_type")=="audio"),None)
        duration=float(info.get("format",{}).get("duration") or 0)
        if not video: failures.append("no_video")
        elif (video.get("width"),video.get("height")) not in ((1080,1920),(1440,2560),(2160,3840)): failures.append("wrong_resolution")
        if not audio: failures.append("no_audio_manual_review_required")
        if duration<15 or duration>60: failures.append("duration_out_of_range")
        if expected_start is not None and expected_end is not None and abs(duration-(expected_end-expected_start))>2: failures.append("duration_mismatch")
        # Decode full media: ffprobe metadata alone cannot establish file integrity.
        decoded=subprocess.run(["ffmpeg","-v","error","-xerror","-i",str(path),"-f","null","-"],capture_output=True,text=True)
        if decoded.returncode!=0: failures.append("decode_failed")
    except (subprocess.CalledProcessError,ValueError,KeyError) as exc:
        failures.append("probe_failed:"+type(exc).__name__)
    return {"status":"PASS_TECHNICAL_ONLY" if not failures else "FAIL","failures":failures,
            "editorial_review":"PENDING","rights_review":"PENDING","human_approval":"PENDING","publish_allowed":False}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--output",default="output")
    args=p.parse_args()
    root=pathlib.Path(args.output)
    manifest_path=root/"manifest.json"
    if not manifest_path.exists(): raise SystemExit("Missing manifest.json")
    manifest=json.loads(manifest_path.read_text())
    for clip in manifest.get("clips",[]):
        clip["technical_qa"]=validate(root/clip["file"],clip.get("start"),clip.get("end"))
    manifest["publishing_allowed"]=False
    manifest["qa_stage"]="technical_only_no_semantic_analysis"
    manifest_path.write_text(json.dumps(manifest,indent=2))
    print(json.dumps({"qa":[{"file":x["file"],"status":x["technical_qa"]["status"]} for x in manifest["clips"]]}))

if __name__=="__main__":
    main()
