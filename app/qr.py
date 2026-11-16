"""QR-код і посилання для приєднання. Власник: Слава."""
import segno

from app.config import PUBLIC_URL


def join_url(code: str, public_url: str = PUBLIC_URL) -> str:
    return f"{public_url.rstrip('/')}/static/play.html?room={code}"


def qr_svg(data: str) -> str:
    """Inline <svg> без XML-декларації, масштабується через CSS (width/height не задані)."""
    return segno.make(data, error="m").svg_inline(scale=1, omitsize=True, dark="#000", light="#fff")
