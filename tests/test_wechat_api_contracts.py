from wewrite.toolkit import wechat_api


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def test_access_token_request_contract(monkeypatch):
    captured = {}
    wechat_api._token_cache.clear()

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _Response({"access_token": "token-1", "expires_in": 7200})

    monkeypatch.setattr(wechat_api.requests, "get", fake_get)
    token = wechat_api.get_access_token("wx-app", "secret-value")

    assert token == "token-1"
    assert captured["url"].endswith("/cgi-bin/token")
    assert captured["params"] == {
        "grant_type": "client_credential",
        "appid": "wx-app",
        "secret": "secret-value",
    }
    assert captured["timeout"] == wechat_api.API_TIMEOUT


def test_body_image_upload_contract(tmp_path, monkeypatch):
    captured = {}
    image = tmp_path / "figure.png"
    image.write_bytes(b"png-bytes")

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        filename, file_handle, content_type = kwargs["files"]["media"]
        captured["filename"] = filename
        captured["content_type"] = content_type
        captured["bytes"] = file_handle.read()
        return _Response({"url": "https://mmbiz.qpic.cn/body-image"})

    monkeypatch.setattr(wechat_api.requests, "post", fake_post)
    url = wechat_api.upload_image("token-2", str(image))

    assert url == "https://mmbiz.qpic.cn/body-image"
    assert captured["url"].endswith("/cgi-bin/media/uploadimg")
    assert captured["params"] == {"access_token": "token-2"}
    assert captured["filename"] == "figure.png"
    assert captured["content_type"] == "image/png"
    assert captured["bytes"] == b"png-bytes"
    assert captured["timeout"] == wechat_api.API_TIMEOUT


def test_cover_permanent_material_upload_contract(tmp_path, monkeypatch):
    captured = {}
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"jpg-bytes")

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        filename, file_handle, content_type = kwargs["files"]["media"]
        captured["filename"] = filename
        captured["content_type"] = content_type
        captured["bytes"] = file_handle.read()
        return _Response({"media_id": "thumb-media-id"})

    monkeypatch.setattr(wechat_api.requests, "post", fake_post)
    media_id = wechat_api.upload_thumb("token-3", str(cover))

    assert media_id == "thumb-media-id"
    assert captured["url"].endswith("/cgi-bin/material/add_material")
    assert captured["params"] == {"access_token": "token-3", "type": "image"}
    assert captured["filename"] == "cover.jpg"
    assert captured["content_type"] == "image/jpeg"
    assert captured["bytes"] == b"jpg-bytes"
    assert captured["timeout"] == wechat_api.API_TIMEOUT
