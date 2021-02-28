import sys
import tempfile
import time
from inspect import cleandoc

import httpx
import pytest

from baize.datastructures import Address, UploadFile
from baize.exceptions import HTTPException
from baize.wsgi import (
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Request,
    Response,
    SendEventResponse,
)


def test_request_environ_interface():
    """
    A Request can be instantiated with a environ, and presents a `Mapping`
    interface.
    """
    request = Request({"type": "http", "method": "GET", "path": "/abc/"})
    assert request["method"] == "GET"
    assert dict(request) == {"type": "http", "method": "GET", "path": "/abc/"}
    assert len(request) == 3


def test_request_url():
    def app(environ, start_response):
        request = Request(environ)
        response = Response(request.method + " " + str(request.url))
        return response(environ, start_response)

    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.get("/123?a=abc")
        assert response.text == "GET http://testserver/123?a=abc"

        response = client.get("https://example.org:123/")
        assert response.text == "GET https://example.org:123/"


def test_request_query_params():
    def app(environ, start_response):
        request = Request(environ)
        params = dict(request.query_params)
        response = JSONResponse({"params": params})
        return response(environ, start_response)

    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.get("/?a=123&b=456")
        assert response.json() == {"params": {"a": "123", "b": "456"}}


def test_request_headers():
    def app(environ, start_response):
        request = Request(environ)
        headers = dict(request.headers)
        headers.pop("user-agent")  # this is httpx version, delete it
        response = JSONResponse({"headers": headers})
        return response(environ, start_response)

    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.get("/", headers={"host": "example.org"})
        assert response.json() == {
            "headers": {
                "host": "example.org",
                "accept-encoding": "gzip, deflate",
                "accept": "*/*",
                "connection": "keep-alive",
            }
        }


def test_request_client():
    def app(environ, start_response):
        request = Request(environ)
        response = JSONResponse(
            {"host": request.client.host, "port": request.client.port}
        )
        return response(environ, start_response)

    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.get("/")
        assert response.json() == {"host": None, "port": None}

    request = Request({"REMOTE_ADDR": "127.0.0.1", "REMOTE_PORT": "62124"})
    assert request.client == Address("127.0.0.1", 62124)


def test_request_body():
    def app(environ, start_response):
        request = Request(environ)
        body = request.body
        response = JSONResponse({"body": body.decode()})
        return response(environ, start_response)

    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.get("/")
        assert response.json() == {"body": ""}

        response = client.post("/", json={"a": "123"})
        assert response.json() == {"body": '{"a": "123"}'}

        response = client.post("/", data="abc")
        assert response.json() == {"body": "abc"}


def test_request_stream():
    def app(environ, start_response):
        request = Request(environ)
        body = b""
        for chunk in request.stream():
            body += chunk
        response = PlainTextResponse(body)
        return response(environ, start_response)

    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.get("/")
        assert response.text == ""

        response = client.post("/", json={"a": "123"})
        assert response.text == '{"a": "123"}'

        response = client.post("/", data="abc")
        assert response.text == "abc"


def test_request_form_urlencoded():
    def app(environ, start_response):
        request = Request(environ)
        form = request.form
        response = JSONResponse({"form": dict(form)})
        return response(environ, start_response)
        request.close()

    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.post("/", data={"abc": "123 @"})
        assert response.json() == {"form": {"abc": "123 @"}}

        with pytest.raises(HTTPException):
            response = client.post(
                "/", data={"abc": "123 @"}, headers={"content-type": "application/json"}
            )


@pytest.mark.skipif("multipart" not in sys.modules, reason="Missing python-multipart")
def test_request_multipart_form():
    def app(environ, start_response):
        request = Request(environ)
        form = request.form
        assert isinstance(form["file-key"], UploadFile)
        assert form["file-key"].read() == b"temporary file"
        response = JSONResponse({"file": form["file-key"].filename})
        request.close()
        return response(environ, start_response)

    with httpx.Client(app=app, base_url="http://testServer/") as client:
        with tempfile.SpooledTemporaryFile(1024) as file:
            file.write(b"temporary file")
            file.seek(0, 0)
            response = client.post("/", data={"abc": "123 @"}, files={"file-key": file})
            assert response.json() == {"file": "None"}


def test_request_body_then_stream():
    def app(environ, start_response):
        request = Request(environ)
        body = request.body
        chunks = b""
        for chunk in request.stream():
            chunks += chunk
        response = JSONResponse({"body": body.decode(), "stream": chunks.decode()})
        return response(environ, start_response)

    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.post("/", data="abc")
        assert response.json() == {"body": "abc", "stream": "abc"}


def test_request_stream_then_body():
    def app(environ, start_response):
        request = Request(environ)
        chunks = b""
        for chunk in request.stream():
            chunks += chunk
        try:
            body = request.body
        except RuntimeError:
            body = b"<stream consumed>"
        response = JSONResponse({"body": body.decode(), "stream": chunks.decode()})
        return response(environ, start_response)

    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.post("/", data="abc")
        assert response.json() == {"body": "<stream consumed>", "stream": "abc"}


def test_request_json():
    def app(environ, start_response):
        request = Request(environ)
        data = request.json
        response = JSONResponse({"json": data})
        return response(environ, start_response)

    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.post("/", json={"a": "123"})
        assert response.json() == {"json": {"a": "123"}}

        with pytest.raises(HTTPException):
            response = client.post(
                "/",
                data={"abc": "123 @"},
                headers={"content-type": "application/x-www-form-urlencoded"},
            )


def test_request_accpet():
    data = "hello world"

    def app(environ, start_response):
        request = Request(environ)
        if request.accepts("application/json"):
            response = JSONResponse({"data": data})
        else:
            response = PlainTextResponse(data)
        return response(environ, start_response)

    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.get("/", headers={"Accept": "application/json"})
        assert response.json() == {"data": data}


# ######################################################################################
# ################################# Responses tests ####################################
# ######################################################################################


def test_unknown_status():
    with httpx.Client(app=Response(b"", 600), base_url="http://testServer/") as client:
        response = client.get("/")
        assert response.status_code == 600


def test_redirect_response():
    def app(environ, start_response):
        if environ["PATH_INFO"] == "/":
            response = PlainTextResponse("hello, world")
        else:
            response = RedirectResponse("/")
        return response(environ, start_response)

    with httpx.Client(app=app, base_url="http://testServer/") as client:
        response = client.get("/redirect")
        assert response.text == "hello, world"
        assert response.url == "http://testserver/"


def test_send_event_response():
    def send_events():
        yield {"data": "hello\nworld"}
        time.sleep(0.2)
        yield {"data": "nothing", "event": "nothing"}
        yield {"event": "only-event"}

    expected_events = (
        cleandoc(
            """
            data: hello
            data: world

            event: nothing
            data: nothing

            event: only-event
            """
        )
        + "\n\n"
    )

    with httpx.Client(
        app=SendEventResponse(send_events(), ping_interval=0.1),
        base_url="http://testServer/",
    ) as client:
        with client.stream("GET", "/") as resp:
            resp.raise_for_status()
            events = ""
            for line in resp.iter_lines():
                events += line
            assert events.replace(": ping\n\n", "") == expected_events

    with httpx.Client(
        app=SendEventResponse(
            send_events(),
            headers={"custom-header": "value"},
            ping_interval=0.1,
        ),
        base_url="http://testServer/",
    ) as client:
        with client.stream("GET", "/") as resp:
            resp.raise_for_status()
            assert resp.headers["custom-header"] == "value"
            events = ""
            for line in resp.iter_lines():
                events += line
            assert events.replace(": ping\n\n", "") == expected_events
