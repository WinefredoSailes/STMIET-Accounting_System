"""My Profile (ADR-048): shared access, self-service details/password/
avatar/theme, persistence across the site, and the safety guards built
alongside it (form-draft never touches password fields)."""

import io
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.foundation.models import UserProfile

User = get_user_model()
pytestmark = pytest.mark.django_db

NEW_PW = "Str0ng-Choice-2026!"


@pytest.fixture(autouse=True)
def isolated_media(tmp_path, settings):
    """Avatar files go to a per-test directory: the dev machine's real
    media/avatars/ must never gain test orphans (which once caused the
    deterministic-name assertion to trip over leftovers)."""
    settings.STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": str(tmp_path / "media"), "base_url": settings.MEDIA_URL},
        },
        "staticfiles": settings.STORAGES["staticfiles"],
    }


@pytest.fixture
def clerk(db):
    u = User.objects.create_user("clerk9", password="old-pass-123", first_name="Cly", last_name="Deput")
    UserProfile.objects.create(user=u, approval_role="staff")
    return u


def _login(client, u):
    assert client.login(username=u.username, password="old-pass-123")


def _img(fmt="PNG", size=(400, 260), color=(180, 40, 40)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, fmt)
    return SimpleUploadedFile("ava", buf.getvalue(), f"image/{fmt.lower()}")


# ---- access / shared route -------------------------------------------------

def test_profile_opens_for_every_role_and_is_never_gated(client, clerk):
    _login(client, clerk)
    assert client.get("/profile/").status_code == 200
    # even an inbox-only custom grant (no work screens at all)
    clerk.profile.screen_access = ["my_approvals"]
    clerk.profile.save()
    assert client.get("/profile/").status_code == 200


def test_anonymous_profile_redirects_to_login(client):
    assert client.get("/profile/").status_code == 302


def test_legacy_user_without_profile_gets_one_on_visit(client, db):
    u = User.objects.create_user("nofx", password="old-pass-123")
    assert not UserProfile.objects.filter(user=u).exists()
    client.force_login(u)
    assert client.get("/profile/").status_code == 200
    assert UserProfile.objects.filter(user=u).exists()


# ---- details ---------------------------------------------------------------

def test_details_update(client, clerk):
    _login(client, clerk)
    resp = client.post("/profile/", {"action": "details", "first_name": "Clara", "last_name": "D.", "email": "clara@firm.co"})
    assert resp.status_code == 302 or resp.status_code == 200
    clerk.refresh_from_db()
    assert clerk.first_name == "Clara" and clerk.email == "clara@firm.co"


def test_details_rejects_bad_email_and_blank_names(client, clerk):
    _login(client, clerk)
    resp = client.post("/profile/", {"action": "details", "first_name": "X", "last_name": "", "email": "not-an-email"})
    assert "valid email" in resp.content.decode()
    clerk.refresh_from_db()
    assert clerk.first_name == "Cly"
    resp = client.post("/profile/", {"action": "details", "first_name": "", "last_name": "", "email": ""})
    assert "at least one name" in resp.content.decode()


# ---- theme -----------------------------------------------------------------

def test_theme_persists_and_applies_site_wide(client, clerk):
    _login(client, clerk)
    resp = client.post("/profile/", {"action": "theme", "theme": "ocean"})
    assert resp.status_code in (200, 302)
    clerk.profile.refresh_from_db()
    assert clerk.profile.theme == "ocean"
    # rendered on every page afterwards
    body = client.get("/").content.decode()
    assert 'data-theme="ocean"' in body


def test_invalid_theme_rejected(client, clerk):
    _login(client, clerk)
    client.post("/profile/", {"action": "theme", "theme": "hot-pink-9000"})
    clerk.profile.refresh_from_db()
    assert clerk.profile.theme == "teal"


def test_picker_renders_all_eight_swatches(client, clerk):
    _login(client, clerk)
    body = client.get("/profile/").content.decode()
    for name in ("teal", "ocean", "indigo", "plum", "sunset", "forest", "blossom", "crimson"):
        assert f'value="{name}"' in body


# ---- password --------------------------------------------------------------

def test_password_wrong_current_is_rejected(client, clerk):
    _login(client, clerk)
    resp = client.post("/profile/", {"action": "password", "old_password": "not-my-password", "new_password1": NEW_PW, "new_password2": NEW_PW})
    body = resp.content.decode()
    assert "not valid" in body or "incorrect" in body.lower()
    clerk.refresh_from_db()
    assert clerk.check_password("old-pass-123")


def test_password_change_success_keeps_session_signed_in(client, clerk):
    _login(client, clerk)
    resp = client.post("/profile/", {"action": "password", "old_password": "old-pass-123", "new_password1": NEW_PW, "new_password2": NEW_PW})
    assert resp.status_code in (200, 302)
    clerk.refresh_from_db()
    assert clerk.check_password(NEW_PW)
    # session survives the rotation (update_session_auth_hash)
    assert client.get("/profile/").status_code == 200


def test_password_fields_have_confirm_wiring(client, clerk):
    _login(client, clerk)
    body = client.get("/profile/").content.decode()
    assert "data-confirm=\"Change your password" in body
    assert "autocomplete=\"new-password\"" in body


# ---- avatar ----------------------------------------------------------------

def test_avatar_upload_square_and_reencoded(client, clerk):
    _login(client, clerk)
    resp = client.post("/profile/", {"action": "avatar", "avatar": _img("PNG", (400, 260))})
    assert resp.status_code in (200, 302)
    clerk.profile.refresh_from_db()
    assert clerk.profile.avatar
    with Image.open(clerk.profile.avatar.path) as im:
        assert im.size == (256, 256)
        assert im.format == "JPEG"


def test_avatar_rejects_non_image_and_too_large(client, clerk, settings):
    _login(client, clerk)
    resp = client.post("/profile/", {"action": "avatar", "avatar": SimpleUploadedFile("x.txt", b"plain text", "text/plain")})
    assert "not a readable image" in resp.content.decode()
    clerk.profile.refresh_from_db()
    assert not clerk.profile.avatar
    big = SimpleUploadedFile("big.png", b"\x00" * (3 * 1024 * 1024), "image/png")
    resp = client.post("/profile/", {"action": "avatar", "avatar": big})
    assert "too large" in resp.content.decode()


def test_avatar_removes(client, clerk):
    _login(client, clerk)
    client.post("/profile/", {"action": "avatar", "avatar": _img()})
    clerk.profile.refresh_from_db()
    assert clerk.profile.avatar
    resp = client.post("/profile/", {"action": "avatar", "remove_avatar": "1"})
    clerk.profile.refresh_from_db()
    assert not clerk.profile.avatar


# ---- chrome integration -----------------------------------------------------

def test_footer_links_profile_with_avatar_or_initials(client, clerk):
    _login(client, clerk)
    body = client.get("/").content.decode()
    assert 'href="/profile/"' in body
    assert "CD" in body  # initials C + D
    # sign-out sits below its own divider and always asks first
    assert 'data-confirm="Are you sure you want to sign out?"' in body
    assert "#i-signout" in body
    client.post("/profile/", {"action": "avatar", "avatar": _img()})
    body = client.get("/").content.decode()
    assert "/media/avatars/" in body


def test_user_management_list_shows_avatars_and_initials(client, db):
    """(ADR-048) uploaded photos appear in the users table; users without
    one fall back to initials."""
    boss = User.objects.create_superuser("bossx", "boss@x.co", "old-pass-123")
    clerk2 = User.objects.create_user("photog", password="old-pass-123", first_name="Pat", last_name="Photo")
    UserProfile.objects.create(user=clerk2, approval_role="staff")
    UserProfile.objects.create(user=boss, approval_role="")

    _login(client, boss)
    client.post("/profile/", {"action": "avatar", "avatar": _img("JPEG", (300, 300))})

    body = client.get("/settings/users/").content.decode()
    assert "/media/avatars/" in body          # the uploaded avatar shows
    assert "PP" in body                        # initials fallback for photog
    assert 'alt=""' in body                    # avatar imgs alt-decorative


def test_missing_avatar_file_falls_back_to_initials(client, clerk):
    """The Render bug: DB reference outliving the file must never render a
    404-inducing <img>."""
    import os

    _login(client, clerk)
    client.post("/profile/", {"action": "avatar", "avatar": _img()})
    clerk.profile.refresh_from_db()
    os.remove(clerk.profile.avatar.path)  # simulate the ephemeral disk wiping it

    assert clerk.profile.avatar_url == ""          # raw reference still set...
    assert bool(clerk.profile.avatar)              # ...so "Remove" stays available
    body = client.get("/").content.decode()
    assert "/media/avatars" not in body            # no <img> emitted anywhere
    assert "CD" in body                            # initials instead
    assert "/media/avatars" not in client.get("/profile/").content.decode()
    assert "/media/avatars" not in client.get("/approvals/").content.decode()


def test_avatar_reupload_uses_one_deterministic_file(client, clerk):
    _login(client, clerk)
    client.post("/profile/", {"action": "avatar", "avatar": _img()})
    clerk.profile.refresh_from_db()
    first = clerk.profile.avatar.name
    assert first == f"avatars/avatar-{clerk.pk}.jpg"

    client.post("/profile/", {"action": "avatar", "avatar": _img("JPEG", (120, 120), (10, 20, 30))})
    clerk.profile.refresh_from_db()
    assert clerk.profile.avatar.name == first      # replaced, no avatar_XXXX suffix

    # and the URL really serves (the prod /media route):
    assert client.get(clerk.profile.avatar.url).status_code == 200
