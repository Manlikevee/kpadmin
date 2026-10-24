from .models import SiteSettings


def site(request):
    try:
        return {"site_settings": SiteSettings.load()}
    except Exception:  # e.g. before migrations have run
        return {}
