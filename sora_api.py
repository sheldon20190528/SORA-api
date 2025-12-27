# sora_api.py
# SORA / DyuAPI API client (multipart upload, job query, download)
import requests
import mimetypes
import tempfile
import os
import base64
import time
from typing import Optional, Dict, Any, Union

def save_bytes_to_tempfile(bytes_data: bytes, suffix: str = ".mp4") -> str:
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="sora_video_")
    try:
        os.close(fd)
        with open(path, "wb") as f:
            f.write(bytes_data)
        return path
    except Exception:
        try:
            os.remove(path)
        except Exception:
            pass
        raise

def is_done_status(status: Optional[str]) -> bool:
    if not status:
        return False
    s = str(status).strip().lower()
    done_states = {"succeeded", "completed", "finished", "done", "success"}
    return s in done_states

class SoraAPIClient:
    def __init__(self, base_url: str, api_key: Optional[str] = None, timeout: int = 60):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def create_video_job(self,
                         endpoint: str,
                         image_path: Optional[str] = None,
                         image_bytes: Optional[bytes] = None,
                         filename: Optional[str] = None,
                         prompt: Optional[str] = None,
                         model: Optional[str] = None,
                         trim: Optional[Union[bool, str]] = None,
                         extra_fields: Optional[Dict[str, str]] = None
                         ) -> Dict[str, Any]:
        """
        Submit a create-video job (multipart/form-data).
        Uses file field name 'input_reference' as in the API sample.
        Returns dict: {status_code, ok, headers, text, json, raw}
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = self._headers()

        files = {}
        data = {}

        # 文件部分 (field name: input_reference)
        if image_bytes is not None:
            fname = filename or "input.png"
            ctype = mimetypes.guess_type(fname)[0] or "application/octet-stream"
            # requests accepts bytes via (filename, bytes, content_type)
            files["input_reference"] = (fname, image_bytes, ctype)
        elif image_path:
            if not os.path.exists(image_path):
                return {"status_code": None, "ok": False, "error": f"file not found: {image_path}"}
            fname = os.path.basename(image_path)
            ctype = mimetypes.guess_type(image_path)[0] or "application/octet-stream"
            files["input_reference"] = (fname, open(image_path, "rb"), ctype)

        # 文本字段
        if prompt is not None:
            data["prompt"] = str(prompt)
        if model is not None:
            data["model"] = str(model)
        if trim is not None:
            data["trim"] = "true" if (str(trim).lower() in ("1", "true", "yes")) else "false"
        if extra_fields:
            for k, v in extra_fields.items():
                data[str(k)] = str(v)

        try:
            resp = requests.post(url, headers=headers, files=files if files else None, data=data if data else None, timeout=self.timeout)
        except requests.RequestException as e:
            # close opened file handle if any
            if files.get("input_reference") and hasattr(files["input_reference"][1], "close"):
                try:
                    files["input_reference"][1].close()
                except Exception:
                    pass
            return {"status_code": None, "ok": False, "error": str(e), "json": None, "text": ""}

        # close file handles
        if files.get("input_reference") and hasattr(files["input_reference"][1], "close"):
            try:
                files["input_reference"][1].close()
            except Exception:
                pass

        return self._build_response(resp)

    def get_job(self, endpoint: str, job_id: str) -> Dict[str, Any]:
        """
        GET job info. endpoint can be '/v1/videos/{id}' or '/v1/videos'
        If endpoint contains '{id}', it will be replaced; otherwise GET {endpoint}/{id}
        """
        if "{id}" in endpoint:
            url = f"{self.base_url}/{endpoint.lstrip('/')}".format(id=job_id)
        else:
            url = f"{self.base_url}/{endpoint.lstrip('/')}/{job_id}"
        headers = self._headers()
        try:
            resp = requests.get(url, headers=headers, timeout=self.timeout)
        except requests.RequestException as e:
            return {"status_code": None, "ok": False, "error": str(e), "json": None, "text": ""}

        return self._build_response(resp)

    def download_url(self, url: str) -> Dict[str, Any]:
        """
        Download arbitrary URL and return wrapper containing raw bytes.
        """
        headers = self._headers()
        try:
            resp = requests.get(url, headers=headers, timeout=self.timeout)
        except requests.RequestException as e:
            return {"status_code": None, "ok": False, "error": str(e), "json": None, "text": "", "raw": None}

        result = self._build_response(resp)
        result["raw"] = resp.content
        return result

    def _build_response(self, resp: requests.Response) -> Dict[str, Any]:
        result = {
            "status_code": resp.status_code,
            "ok": resp.ok,
            "headers": dict(resp.headers),
            "text": resp.text,
            "json": None,
            "raw": resp.content
        }
        ct = resp.headers.get("Content-Type", "")
        if "application/json" in ct or (resp.text and resp.text.strip().startswith("{")):
            try:
                result["json"] = resp.json()
            except Exception:
                result["json"] = None
        return result