from flask.testing import FlaskClient


def test_healthz_returns_ok(client: FlaskClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}
