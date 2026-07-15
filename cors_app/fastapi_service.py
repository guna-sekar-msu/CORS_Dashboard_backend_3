"""
FastAPI Proxy Service - Django acts as POSTMAN
Just forwards requests to FastAPI without any preprocessing
All data handling happens in FastAPI (reading files, S3, processing)
"""

import requests
import json
from urllib.parse import urljoin


class FastAPIProxyService:
    """Simple proxy service to forward requests to FastAPI"""
    
    FASTAPI_BASE_URL = "http://127.0.0.1:8000"
    
    @staticmethod
    def proxy_request(endpoint=None, url=None, method='GET', headers=None, params=None, data=None, json_body=None, timeout=30):
        """
        Generic proxy request to FastAPI.
        
        Args:
            endpoint: FastAPI endpoint path (e.g. '/stations/MYCS2')
            url: full FastAPI URL (overrides endpoint)
            method: HTTP method
            headers: dict of request headers
            params: URL query parameters
            data: request body as form data or raw text
            json_body: request body as JSON
            timeout: request timeout in seconds
        
        Returns:
            dict: proxied response metadata and body
        """
        if not url and not endpoint:
            return {"error": "Missing endpoint or url"}

        target_url = url or urljoin(FastAPIProxyService.FASTAPI_BASE_URL, endpoint)
        forwarded_headers = headers or {}
        filtered_headers = {
            k: v
            for k, v in forwarded_headers.items()
            if k.lower() not in {
                'host', 'content-length', 'accept-encoding', 'connection', 'transfer-encoding'
            }
        }

        try:
            response = requests.request(
                method=method.upper(),
                url=target_url,
                headers=filtered_headers,
                params=params,
                data=data,
                json=json_body,
                timeout=timeout
            )

            response_headers = dict(response.headers)
            content_type = response.headers.get('Content-Type', '')
            if not content_type:
                content_type = response_headers.get('content-type', '')

            raw_text = response.text
            body = raw_text

            try:
                if 'application/json' in content_type.lower():
                    parsed = json.loads(raw_text)
                    if isinstance(parsed, str):
                        try:
                            body = json.loads(parsed)
                        except ValueError:
                            body = parsed
                    else:
                        body = parsed
                else:
                    body = raw_text
            except ValueError:
                body = raw_text

            return {
                "status_code": response.status_code,
                "headers": response_headers,
                "content_type": content_type,
                "body": body
            }

        except requests.exceptions.Timeout:
            return {"error": "FastAPI request timeout", "type": "timeout_error"}
        except requests.exceptions.ConnectionError:
            return {"error": "Cannot connect to FastAPI", "type": "connection_error"}
        except requests.exceptions.RequestException as e:
            return {"error": str(e), "type": "request_error"}
        except Exception as e:
            return {"error": str(e), "type": "unknown_error"}
