import asyncio


async def _login(client, username, password):
    return await client.post("/login", json={"username": username, "password": password})


async def test_health(client):
    assert (await client.get("/health")).json() == {"status": "ok"}


async def test_seeded_user_can_log_in_and_read_profile(client):
    response = await _login(client, "user007", "pass-user007")
    assert response.status_code == 200
    token = response.json()["token"]

    me = await client.get("/me", headers={"Authorization": f"Bearer {token}"})

    assert me.status_code == 200
    assert me.json()["username"] == "user007"
    assert me.json()["display_name"] == "User 7"


async def test_wrong_password_is_rejected(client):
    assert (await _login(client, "user007", "pass-user008")).status_code == 401


async def test_unknown_user_is_rejected(client):
    assert (await _login(client, "nobody", "whatever")).status_code == 401


async def test_me_requires_a_valid_token(client):
    assert (await client.get("/me")).status_code == 401
    assert (await client.get("/me", headers={"Authorization": "Bearer not-a-token"})).status_code == 401


async def test_registered_password_is_stored_with_full_strength_hashing(client, db, new_user):
    username, password = new_user

    stored = await db.fetchval("SELECT password_hash FROM users WHERE username = $1", username)

    algorithm, iterations, salt, digest = stored.split("$")
    assert algorithm == "pbkdf2_sha256"
    assert int(iterations) >= 200_000
    assert len(bytes.fromhex(salt)) >= 16
    assert password not in stored
    assert (await _login(client, username, password)).status_code == 200


async def test_changed_password_replaces_the_old_one(client, new_user):
    username, password = new_user
    token = (await _login(client, username, password)).json()["token"]

    changed = await client.post("/password", headers={"Authorization": f"Bearer {token}"},
                                json={"old_password": password, "new_password": "a brand new secret"})

    assert changed.status_code == 204
    assert (await _login(client, username, password)).status_code == 401
    assert (await _login(client, username, "a brand new secret")).status_code == 200


async def test_password_change_requires_the_old_password(client, new_user):
    username, password = new_user
    token = (await _login(client, username, password)).json()["token"]

    response = await client.post("/password", headers={"Authorization": f"Bearer {token}"},
                                 json={"old_password": "not it at all", "new_password": "a brand new secret"})

    assert response.status_code == 401
    assert (await _login(client, username, password)).status_code == 200


async def test_concurrent_logins_all_get_distinct_sessions(client):
    users = [f"user{i:03d}" for i in range(20, 32)]

    responses = await asyncio.gather(*(_login(client, u, f"pass-{u}") for u in users))

    assert all(r.status_code == 200 for r in responses)
    tokens = [r.json()["token"] for r in responses]
    assert len(set(tokens)) == len(tokens)
    for user, token in zip(users, tokens):
        me = await client.get("/me", headers={"Authorization": f"Bearer {token}"})
        assert me.json()["username"] == user
