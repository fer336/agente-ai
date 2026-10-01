from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_the_clinic_location_image_is_served_publicly_as_a_jpeg():
    response = client.get("/public/clinic-location.jpg")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content[:3] == b"\xff\xd8\xff"


def test_the_aligners_options_image_is_served_publicly_as_a_jpeg():
    response = client.get("/public/alineadores-opciones.jpg")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content[:3] == b"\xff\xd8\xff"


def test_the_public_folder_has_no_directory_listing():
    assert client.get("/public/").status_code == 404
    assert client.get("/public").status_code in (404, 307)


def test_a_path_outside_the_public_folder_is_not_served():
    for path in (
        "/public/../admin/app.js",
        "/public/%2e%2e/admin/app.js",
        "/public/..%2fadmin%2fapp.js",
        "/public/../../main.py",
    ):
        assert client.get(path).status_code == 404, path
