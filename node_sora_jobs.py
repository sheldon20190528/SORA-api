# node_sora_jobs.py
# ComfyUI nodes: CreateVideoJob, GetVideoJobStatus (with polling), DownloadVideoResult
# Put this file and sora_api.py into ComfyUI's custom nodes directory and restart ComfyUI.

from typing import Tuple, Optional
import json, os, time, base64
from sora_api import SoraAPIClient, save_bytes_to_tempfile, is_done_status

class CreateVideoJob:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "base_url": ("STRING", {"default": "https://api.dyuapi.com"}),
                "endpoint": ("STRING", {"default": "/v1/videos"}),  # POST endpoint
                "api_key": ("STRING", {"default": ""}),
                "prompt": ("STRING", {"default": "换一个风格 广告"}),
            },
            "optional": {
                "file_path": ("STRING", {"default": ""}),  # 本地文件路径
                "image_base64": ("STRING", {"default": ""}), # base64 数据优先
                "filename": ("STRING", {"default": "input.png"}),
                "model": ("STRING", {"default": "sora2-portrait-15s"}),
                "trim": ("BOOLEAN", {"default": True}),
                "extra_fields_json": ("STRING", {"default": ""}),
                "timeout": ("INT", {"default": 60}),
            }
        }

    RETURN_TYPES = ("JSON", "STRING")  # (resp_dict, job_id)
    FUNCTION = "call"
    CATEGORY = "SORA"

    def call(self,
             base_url: str,
             endpoint: str,
             api_key: str,
             prompt: str,
             file_path: str = "",
             image_base64: str = "",
             filename: str = "input.png",
             model: str = "sora2-portrait-15s",
             trim: bool = True,
             extra_fields_json: str = "",
             timeout: int = 60
             ) -> Tuple[Optional[dict], Optional[str]]:

        extra = {}
        if extra_fields_json:
            try:
                extra = json.loads(extra_fields_json)
            except Exception as e:
                return ({"ok": False, "error": f"extra_fields_json parse error: {e}"}, "")

        client = SoraAPIClient(base_url=base_url, api_key=api_key or None, timeout=timeout)

        image_bytes = None
        if image_base64:
            b64 = image_base64
            if b64.startswith("data:"):
                try:
                    b64 = b64.split(",", 1)[1]
                except Exception:
                    pass
            try:
                image_bytes = base64.b64decode(b64)
            except Exception as e:
                return ({"ok": False, "error": f"image_base64 decode error: {e}"}, "")

        resp = client.create_video_job(endpoint=endpoint,
                                       image_path=file_path if (not image_bytes and file_path) else None,
                                       image_bytes=image_bytes,
                                       filename=filename,
                                       prompt=prompt,
                                       model=model,
                                       trim=trim,
                                       extra_fields=extra)

        job_id = ""
        j = resp.get("json") or {}
        # 常见字段： id
        for key in ("id", "video_id", "job_id", "task_id"):
            if isinstance(j.get(key), str) and j.get(key):
                job_id = j.get(key)
                break

        return (resp, job_id)


class GetVideoJobStatus:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "base_url": ("STRING", {"default": "https://api.dyuapi.com"}),
                "endpoint": ("STRING", {"default": "/v1/videos/{id}"}),  # 支持 {id} 或 /v1/videos
                "api_key": ("STRING", {"default": ""}),
                "job_id": ("STRING", {"default": ""}),
            },
            "optional": {
                "poll": ("BOOLEAN", {"default": False}),  # 是否轮询直到完成
                "poll_interval": ("INT", {"default": 3}), # 秒
                "poll_timeout": ("INT", {"default": 120}), # 秒，轮询总超时
                "timeout": ("INT", {"default": 30})
            }
        }

    RETURN_TYPES = ("JSON", "STRING")  # (resp_dict, status)
    FUNCTION = "call"
    CATEGORY = "SORA"

    def call(self,
             base_url: str,
             endpoint: str,
             api_key: str,
             job_id: str,
             poll: bool = False,
             poll_interval: int = 3,
             poll_timeout: int = 120,
             timeout: int = 30
             ) -> Tuple[Optional[dict], Optional[str]]:

        client = SoraAPIClient(base_url=base_url, api_key=api_key or None, timeout=timeout)

        start = time.time()
        while True:
            resp = client.get_job(endpoint=endpoint, job_id=job_id)
            j = resp.get("json") or {}
            status = None
            # common status keys
            for k in ("status", "state"):
                if isinstance(j.get(k), (str,)) and j.get(k):
                    status = str(j.get(k))
                    break
            if not status:
                status = resp.get("text") or ""

            if poll:
                if is_done_status(status):
                    return (resp, status)
                elapsed = time.time() - start
                if elapsed >= poll_timeout:
                    return (resp, status)
                time.sleep(max(0.5, poll_interval))
                continue
            else:
                return (resp, status)


class DownloadVideoResult:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "base_url": ("STRING", {"default": "https://api.dyuapi.com"}),
                "endpoint": ("STRING", {"default": "/v1/videos/{id}"}),
                "api_key": ("STRING", {"default": ""}),
                "job_id": ("STRING", {"default": ""}),
            },
            "optional": {
                "download_field": ("STRING", {"default": ""}),  # 指定包含下载地址或 base64 的字段名，留空自动检测
                "timeout": ("INT", {"default": 30})
            }
        }

    RETURN_TYPES = ("JSON", "STRING")  # (resp_dict, saved_video_path)
    FUNCTION = "call"
    CATEGORY = "SORA"

    def call(self,
             base_url: str,
             endpoint: str,
             api_key: str,
             job_id: str,
             download_field: str = "",
             timeout: int = 30
             ) -> Tuple[Optional[dict], Optional[str]]:

        client = SoraAPIClient(base_url=base_url, api_key=api_key or None, timeout=timeout)
        resp = client.get_job(endpoint=endpoint, job_id=job_id)
        j = resp.get("json") or {}
        saved_path = ""

        # 指定字段优先
        if download_field:
            v = j.get(download_field)
            if isinstance(v, str) and v.startswith("http"):
                dl = client.download_url(v)
                if dl.get("ok"):
                    try:
                        saved_path = save_bytes_to_tempfile(dl.get("raw") or b"", suffix=".mp4")
                        return (resp, saved_path)
                    except Exception:
                        return (resp, "")
            if isinstance(v, str) and len(v) > 100:
                try:
                    b = base64.b64decode(v)
                    saved_path = save_bytes_to_tempfile(b, suffix=".mp4")
                    return (resp, saved_path)
                except Exception:
                    pass

        # 常用字段检测
        for k in ("video_url", "url", "download_url", "video"):
            v = j.get(k)
            if isinstance(v, str) and v.startswith("http"):
                try:
                    dl = client.download_url(v)
                    if dl.get("ok"):
                        saved_path = save_bytes_to_tempfile(dl.get("raw") or b"", suffix=".mp4")
                        return (resp, saved_path)
                except Exception:
                    pass

        for k in ("video_base64", "video_b64", "b64"):
            v = j.get(k)
            if isinstance(v, str) and len(v) > 100:
                try:
                    b = base64.b64decode(v)
                    saved_path = save_bytes_to_tempfile(b, suffix=".mp4")
                    return (resp, saved_path)
                except Exception:
                    pass

        # nested outputs
        if isinstance(j.get("outputs"), list) and len(j["outputs"]) > 0:
            first = j["outputs"][0]
            if isinstance(first, dict):
                for k in ("url", "download_url", "video_url"):
                    v = first.get(k)
                    if isinstance(v, str) and v.startswith("http"):
                        try:
                            dl = client.download_url(v)
                            if dl.get("ok"):
                                saved_path = save_bytes_to_tempfile(dl.get("raw") or b"", suffix=".mp4")
                                return (resp, saved_path)
                        except Exception:
                            pass

        if isinstance(j.get("result"), dict):
            for k in ("url", "video_url", "download_url"):
                v = j["result"].get(k)
                if isinstance(v, str) and v.startswith("http"):
                    try:
                        dl = client.download_url(v)
                        if dl.get("ok"):
                            saved_path = save_bytes_to_tempfile(dl.get("raw") or b"", suffix=".mp4")
                            return (resp, saved_path)
                    except Exception:
                        pass

        # raw response check
        ct = resp.get("headers", {}).get("Content-Type", "")
        raw = resp.get("raw")
        if raw and isinstance(ct, str) and ct.startswith("video"):
            try:
                saved_path = save_bytes_to_tempfile(raw, suffix=".mp4")
                return (resp, saved_path)
            except Exception:
                pass

        return (resp, saved_path)


NODE_CLASS_MAPPINGS = {
    "CreateVideoJob": CreateVideoJob,
    "GetVideoJobStatus": GetVideoJobStatus,
    "DownloadVideoResult": DownloadVideoResult
}